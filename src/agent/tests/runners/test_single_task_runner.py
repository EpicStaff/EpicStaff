"""
Tests for SingleTaskRunner.

Uses lightweight fakes for Emitter, AgentResolver, and AgentLoop so the
runner's orchestration logic is tested in isolation from I/O.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from app.emitters.base import Emitter
from app.exceptions import AgentServiceError, SchemaValidationError
from app.llm.client import LLMChunk
from app.loop.agent_loop import AgentLoop
from app.loop.context import AgentContext
from app.loop.stop_policy import StopPolicy
from app.output.enforcer import EnforcementResult
from app.resources.resolver import AgentResolver, ResolvedAgent
from app.runners.deps import RunnerDependencies
from app.runners.single_task import SingleTaskRunner
from app.tools.registry import ToolRegistry, ToolSpec
from app.tools.system_tools.structured_output import ANSWER_TOOL
from shared.models.agent_service import (
    AgentRequest,
    AgentSpec,
    LoopResult,
    RunType,
    TokenUsage,
    ToolResult,
)
from shared.models.ai_providers import LLMConfigData, LLMData


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeEmitter(Emitter):
    def __init__(self) -> None:
        self.started: list = []
        self.finals: list[LoopResult] = []
        self.errors: list[Exception] = []
        self.warnings: list[str] = []

    async def on_start(self, request) -> None:
        self.started.append(request)

    async def on_chunk(self, chunk: LLMChunk) -> None:
        pass

    async def on_tool_call(self, call: object) -> None:
        pass

    async def on_tool_result(self, result: ToolResult) -> None:
        pass

    async def on_warning(self, message: str) -> None:
        self.warnings.append(message)

    async def on_final(self, result: LoopResult) -> None:
        self.finals.append(result)

    async def on_error(self, error: Exception) -> None:
        self.errors.append(error)


CANNED_RESULT = LoopResult(
    final_text="Done.",
    tool_invocations=0,
    iterations=1,
    stop_reason="completed",
)


class FakeLoop(AgentLoop):
    """Records context.messages snapshot at call time; returns canned result."""

    def __init__(self) -> None:
        self.received_messages: list[list[dict]] = []

    async def run(self, context, tools, emitter, stop) -> LoopResult:
        self.received_messages.append(list(context.messages))
        return CANNED_RESULT


class AnswerToolLoop(AgentLoop):
    """Loop that calls ANSWER_TOOL with scripted args on each run() call.

    Used to drive the enforcer in integration-style tests without mocking it.
    Script entries are (args_or_none, token_usage):
    - args_or_none=None → tool NOT called (simulates LLM ignoring tool).
    - args_or_none=dict → tool called with those args.
    Also tracks how many times run() was invoked (split by phase: first call is
    the main loop, subsequent calls are enforcer turns).
    """

    def __init__(self, script: list[tuple[dict | None, TokenUsage]]) -> None:
        self._script = list(script)
        self.call_count = 0

    async def run(
        self,
        context: AgentContext,
        tools: ToolRegistry,
        emitter: Emitter,
        stop: StopPolicy,
    ) -> LoopResult:
        self.call_count += 1
        args, token_usage = self._script.pop(0)

        if args is not None and ANSWER_TOOL in {s.name for s in tools.tool_specs()}:
            await tools.execute(ANSWER_TOOL, args)

        return LoopResult(
            final_text="plain text" if args is None else None,
            tool_invocations=1 if args is not None else 0,
            iterations=1,
            stop_reason="completed",
            token_usage=token_usage,
        )


class RaisingEnforcerLoop(AgentLoop):
    """Always raises SchemaValidationError on the second call (simulating enforcer failure)."""

    def __init__(self) -> None:
        self.call_count = 0

    async def run(
        self,
        context: AgentContext,
        tools: ToolRegistry,
        emitter: Emitter,
        stop: StopPolicy,
    ) -> LoopResult:
        self.call_count += 1
        if self.call_count == 1:
            return LoopResult(
                final_text="something",
                tool_invocations=0,
                iterations=1,
                stop_reason="completed",
                token_usage=TokenUsage(),
            )
        raise SchemaValidationError("schema failed")


class FakeResolver:
    """Returns a ResolvedAgent with a real AgentContext and empty ToolRegistry."""

    async def resolve(
        self, agent: AgentSpec, request: AgentRequest, knowledge_sink=None
    ) -> ResolvedAgent:
        context = AgentContext(
            agent=agent,
            attachments=[],
            correlation_id=request.correlation_id,
        )
        return ResolvedAgent(
            agent_id=agent.id,
            context=context,
            tools=ToolRegistry(),
            attachments=[],
        )


class FakeResolverWithTools:
    """Returns a ResolvedAgent with one registered tool so has_tools=True."""

    async def resolve(
        self, agent: AgentSpec, request: AgentRequest, knowledge_sink=None
    ) -> ResolvedAgent:
        context = AgentContext(
            agent=agent,
            attachments=[],
            correlation_id=request.correlation_id,
        )
        registry = ToolRegistry()
        registry.register(
            ToolSpec(name="some_tool", description="a tool"),
            lambda args: ToolResult(tool_call_id="", content="ok"),
        )
        return ResolvedAgent(
            agent_id=agent.id,
            context=context,
            tools=registry,
            attachments=[],
        )


class RaisingResolver:
    """Raises on resolve to simulate resolver failure."""

    async def resolve(
        self, agent: AgentSpec, request: AgentRequest, knowledge_sink=None
    ) -> ResolvedAgent:
        raise RuntimeError("resolver exploded")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _agent_spec(schema_max_retries: int | None = None) -> AgentSpec:
    return AgentSpec(
        id=12,
        name="researcher",
        instructions="You research topics thoroughly.",
        llm=LLMData(provider="openai", config=LLMConfigData(model="gpt-4o")),
        max_iter=5,
        schema_max_retries=schema_max_retries,
    )


def _request(payload: dict, agents: list[AgentSpec] | None = None) -> AgentRequest:
    return AgentRequest(
        correlation_id="test-corr",
        run_type=RunType.SINGLE_TASK,
        agents=agents if agents is not None else [_agent_spec()],
        payload=payload,
    )


def _runner(resolver=None, loop=None) -> SingleTaskRunner:
    resolver = resolver or FakeResolver()
    loop = loop or FakeLoop()
    deps = RunnerDependencies(resolver=resolver, loop=loop)
    return SingleTaskRunner(deps)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_happy_path_single_agent():
    emitter = FakeEmitter()
    fake_loop = FakeLoop()
    runner = _runner(loop=fake_loop)
    request = _request({"task_instructions": "Do X"})

    await runner.execute(request, emitter)

    assert len(emitter.started) == 1
    assert emitter.finals == [CANNED_RESULT]
    assert emitter.finals[0].tasks is None
    assert emitter.errors == []

    messages = fake_loop.received_messages[0]
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert "researcher" in messages[0]["content"]
    assert messages[1]["role"] == "user"
    assert messages[1]["content"] == "Do X"


async def test_payload_uses_prompt_fallback_key():
    """'prompt' key works as fallback when 'task_instructions' is absent."""
    emitter = FakeEmitter()
    fake_loop = FakeLoop()
    runner = _runner(loop=fake_loop)
    request = _request({"prompt": "Summarize."})

    await runner.execute(request, emitter)

    messages = fake_loop.received_messages[0]
    user_message = next(m for m in messages if m["role"] == "user")
    assert user_message["content"] == "Summarize."
    assert emitter.errors == []


async def test_missing_task_instructions_calls_on_error():
    emitter = FakeEmitter()
    runner = _runner()
    request = _request({"output_schema": {"type": "object"}})

    await runner.execute(request, emitter)

    assert len(emitter.errors) == 1
    assert isinstance(emitter.errors[0], AgentServiceError)
    assert emitter.finals == []


async def test_resolver_raises_calls_on_error():
    emitter = FakeEmitter()
    runner = _runner(resolver=RaisingResolver())
    request = _request({"task_instructions": "Do something."})

    await runner.execute(request, emitter)

    assert len(emitter.errors) == 1
    assert isinstance(emitter.errors[0], RuntimeError)
    assert emitter.finals == []


async def test_on_start_called_once_before_loop():
    emitter = FakeEmitter()
    fake_loop = FakeLoop()
    runner = _runner(loop=fake_loop)
    request = _request({"task_instructions": "Check this."})

    await runner.execute(request, emitter)

    assert len(emitter.started) == 1
    assert emitter.started[0] is request


# ---------------------------------------------------------------------------
# output_schema enforcement tests
# ---------------------------------------------------------------------------


async def test_output_schema_no_tools_skips_plain_loop():
    """output_schema + no tools → enforcer only, no plain loop.run."""
    emitter = FakeEmitter()
    schema = {
        "type": "object",
        "properties": {"x": {"type": "string"}},
        "required": ["x"],
    }
    usage = TokenUsage(prompt_tokens=3, completion_tokens=1, total_tokens=4)
    answer_loop = AnswerToolLoop([({"x": "result"}, usage)])
    runner = _runner(loop=answer_loop)
    request = _request({"task_instructions": "Do X", "output_schema": schema})

    with patch("app.runners.single_task._schema_max_retries", return_value=2):
        await runner.execute(request, emitter)

    assert emitter.errors == []
    assert len(emitter.finals) == 1
    final = emitter.finals[0]
    assert json.loads(final.final_text) == {"x": "result"}
    assert final.structured_output == {"x": "result"}
    assert final.stop_reason == "schema_satisfied"
    # Enforcer uses 1 loop call; the plain loop is never called
    assert answer_loop.call_count == 1
    # No-tools path: reported counts come solely from the enforcer's turn.
    assert final.iterations == 1
    assert final.tool_invocations == 1


async def test_output_schema_with_tools_runs_loop_then_enforces():
    """output_schema + tools → plain loop first, then enforcer."""
    emitter = FakeEmitter()
    schema = {
        "type": "object",
        "properties": {"y": {"type": "integer"}},
        "required": ["y"],
    }
    plain_usage = TokenUsage(prompt_tokens=5, completion_tokens=2, total_tokens=7)
    enforce_usage = TokenUsage(prompt_tokens=3, completion_tokens=1, total_tokens=4)
    # First call: plain loop (no ANSWER_TOOL registered, args=None handled by AnswerToolLoop)
    # Second call: enforcer loop (ANSWER_TOOL registered, args provided)
    answer_loop = AnswerToolLoop(
        [
            (None, plain_usage),  # plain loop turn (no ANSWER_TOOL in registry)
            ({"y": 42}, enforce_usage),  # enforcer turn
        ]
    )
    runner = _runner(resolver=FakeResolverWithTools(), loop=answer_loop)
    request = _request({"task_instructions": "Do Y", "output_schema": schema})

    with patch("app.runners.single_task._schema_max_retries", return_value=2):
        await runner.execute(request, emitter)

    assert emitter.errors == []
    assert len(emitter.finals) == 1
    final = emitter.finals[0]
    assert json.loads(final.final_text) == {"y": 42}
    assert final.structured_output == {"y": 42}
    assert final.stop_reason == "schema_satisfied"
    # Total token usage = plain_usage + enforce_usage
    assert final.token_usage.prompt_tokens == 8
    assert final.token_usage.total_tokens == 11
    assert answer_loop.call_count == 2
    # Tools path: plain loop's iterations/tool_invocations (1, 0) plus the
    # enforcer's own turn (1, 1) — the enforcer's counts must not be dropped.
    assert final.iterations == 2
    assert final.tool_invocations == 1


async def test_schema_validation_error_calls_on_error():
    """SchemaValidationError from enforcer → on_error called, on_final not."""
    emitter = FakeEmitter()
    schema = {
        "type": "object",
        "properties": {"z": {"type": "string"}},
        "required": ["z"],
    }
    # Loop never calls the tool → enforcer exhausts retries → SchemaValidationError
    # Provide enough None entries for max_retries+1 attempts (2 retries → 3 entries)
    answer_loop = AnswerToolLoop(
        [
            (None, TokenUsage()),
            (None, TokenUsage()),
            (None, TokenUsage()),
        ]
    )
    runner = _runner(loop=answer_loop)
    request = _request({"task_instructions": "Do Z", "output_schema": schema})

    with patch("app.runners.single_task._schema_max_retries", return_value=2):
        await runner.execute(request, emitter)

    assert len(emitter.errors) == 1
    assert isinstance(emitter.errors[0], SchemaValidationError)
    assert emitter.finals == []


async def test_no_output_schema_uses_single_plain_loop():
    """No output_schema → plain loop only, no enforcer, on_final with canned result."""
    emitter = FakeEmitter()
    fake_loop = FakeLoop()
    runner = _runner(loop=fake_loop)
    request = _request({"task_instructions": "Plain task"})

    await runner.execute(request, emitter)

    assert emitter.errors == []
    assert emitter.finals == [CANNED_RESULT]
    assert emitter.finals[0].structured_output is None
    assert len(fake_loop.received_messages) == 1


# ---------------------------------------------------------------------------
# Tests: main loop failure with output_schema + tools
# ---------------------------------------------------------------------------


class FailureLoop(AgentLoop):
    """Returns a failure LoopResult on the first call; tracks call count."""

    def __init__(self, stop_reason: str, error: str) -> None:
        self._stop_reason = stop_reason
        self._error = error
        self.call_count = 0

    async def run(
        self,
        context,
        tools,
        emitter,
        stop,
    ) -> LoopResult:
        self.call_count += 1
        return LoopResult(
            final_text=None,
            tool_invocations=0,
            iterations=0,
            stop_reason=self._stop_reason,
            token_usage=TokenUsage(),
            error=self._error,
        )


async def test_with_tools_and_schema_main_loop_failure_skips_enforcer():
    """With tools + output_schema: main loop llm_error → on_error called, enforcer never invoked, on_final not called."""
    emitter = FakeEmitter()
    schema = {
        "type": "object",
        "properties": {"x": {"type": "string"}},
        "required": ["x"],
    }
    loop = FailureLoop(stop_reason="llm_error", error="rate limited")
    runner = _runner(resolver=FakeResolverWithTools(), loop=loop)
    request = _request({"task_instructions": "Do X", "output_schema": schema})

    with patch("app.runners.single_task._schema_max_retries", return_value=2):
        await runner.execute(request, emitter)

    assert len(emitter.errors) == 1
    assert "rate limited" in str(emitter.errors[0])
    assert emitter.finals == []
    assert loop.call_count == 1


async def test_with_tools_and_schema_timeout_skips_enforcer():
    """With tools + output_schema: main loop timeout → on_error called, enforcer never invoked."""
    emitter = FakeEmitter()
    schema = {
        "type": "object",
        "properties": {"x": {"type": "string"}},
        "required": ["x"],
    }
    loop = FailureLoop(stop_reason="timeout", error="execution exceeded 60s")
    runner = _runner(resolver=FakeResolverWithTools(), loop=loop)
    request = _request({"task_instructions": "Do X", "output_schema": schema})

    with patch("app.runners.single_task._schema_max_retries", return_value=2):
        await runner.execute(request, emitter)

    assert len(emitter.errors) == 1
    assert "execution exceeded 60s" in str(emitter.errors[0])
    assert emitter.finals == []
    assert loop.call_count == 1


# ---------------------------------------------------------------------------
# Tests: agent.schema_max_retries overrides / falls back to settings
# ---------------------------------------------------------------------------


async def test_agent_schema_max_retries_zero_overrides_settings_default():
    """agent.schema_max_retries=0 → enforcer built with 0, settings fn not used."""
    emitter = FakeEmitter()
    schema = {
        "type": "object",
        "properties": {"x": {"type": "string"}},
        "required": ["x"],
    }
    usage = TokenUsage(prompt_tokens=3, completion_tokens=1, total_tokens=4)
    answer_loop = AnswerToolLoop([({"x": "result"}, usage)])
    runner = _runner(loop=answer_loop)
    agent = _agent_spec(schema_max_retries=0)
    request = _request(
        {"task_instructions": "Do X", "output_schema": schema}, agents=[agent]
    )

    with (
        patch("app.runners.single_task._schema_max_retries") as settings_fn,
        patch("app.runners.task_execution.StructuredOutputEnforcer") as enforcer_class,
    ):
        enforcer_class.return_value.enforce = AsyncMock(
            return_value=EnforcementResult(
                parsed={"x": "result"},
                token_usage=usage,
                iterations=1,
                tool_invocations=1,
            )
        )
        await runner.execute(request, emitter)

    settings_fn.assert_not_called()
    enforcer_class.assert_called_once_with(runner._deps.loop, 0)


async def test_agent_schema_max_retries_none_falls_back_to_settings():
    """agent.schema_max_retries=None → settings fn value used for enforcer retries."""
    emitter = FakeEmitter()
    schema = {
        "type": "object",
        "properties": {"x": {"type": "string"}},
        "required": ["x"],
    }
    usage = TokenUsage(prompt_tokens=3, completion_tokens=1, total_tokens=4)
    answer_loop = AnswerToolLoop([({"x": "result"}, usage)])
    runner = _runner(loop=answer_loop)
    agent = _agent_spec(schema_max_retries=None)
    request = _request(
        {"task_instructions": "Do X", "output_schema": schema}, agents=[agent]
    )

    with (
        patch(
            "app.runners.single_task._schema_max_retries", return_value=7
        ) as settings_fn,
        patch("app.runners.task_execution.StructuredOutputEnforcer") as enforcer_class,
    ):
        enforcer_class.return_value.enforce = AsyncMock(
            return_value=EnforcementResult(
                parsed={"x": "result"},
                token_usage=usage,
                iterations=1,
                tool_invocations=1,
            )
        )
        await runner.execute(request, emitter)

    settings_fn.assert_called_once()
    enforcer_class.assert_called_once_with(runner._deps.loop, 7)
