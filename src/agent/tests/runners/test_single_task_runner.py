"""
Tests for SingleTaskRunner.

Uses lightweight fakes for Emitter, AgentResolver, and AgentLoop so the
runner's orchestration logic is tested in isolation from I/O.
"""

from __future__ import annotations

import json

import pytest
import settings

from app.emitters.base import Emitter
from app.exceptions import AgentServiceError, SchemaValidationError
from app.llm.client import LLMChunk
from app.loop.agent_loop import AgentLoop
from app.loop.context import AgentContext
from app.loop.stop_policy import StopPolicy
from app.resources.resolver import ResolvedAgent
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
from tests.cancellation import never_cancelled
from tests.log_capture import log_line_starting_with, capture_logs_at

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
        self, agent: AgentSpec, request: AgentRequest, knowledge_sink=None, *, is_cancelled
    ) -> ResolvedAgent:
        context = AgentContext(
            agent=agent,
            attachments=[],
            correlation_id=request.correlation_id,
            is_cancelled=is_cancelled,
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
        self, agent: AgentSpec, request: AgentRequest, knowledge_sink=None, *, is_cancelled
    ) -> ResolvedAgent:
        context = AgentContext(
            agent=agent,
            attachments=[],
            correlation_id=request.correlation_id,
            is_cancelled=is_cancelled,
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
        self, agent: AgentSpec, request: AgentRequest, knowledge_sink=None, *, is_cancelled
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


@pytest.fixture(autouse=True)
def service_schema_max_retries(monkeypatch):
    monkeypatch.setattr(settings, "AGENT_SCHEMA_MAX_RETRIES", 2)


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

    await runner.execute(request, emitter, is_cancelled=never_cancelled)

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

    await runner.execute(request, emitter, is_cancelled=never_cancelled)

    messages = fake_loop.received_messages[0]
    user_message = next(m for m in messages if m["role"] == "user")
    assert user_message["content"] == "Summarize."
    assert emitter.errors == []


async def test_missing_task_instructions_calls_on_error():
    emitter = FakeEmitter()
    runner = _runner()
    request = _request({"output_schema": {"type": "object"}})

    await runner.execute(request, emitter, is_cancelled=never_cancelled)

    assert len(emitter.errors) == 1
    assert isinstance(emitter.errors[0], AgentServiceError)
    assert emitter.finals == []


async def test_resolver_raises_calls_on_error():
    emitter = FakeEmitter()
    runner = _runner(resolver=RaisingResolver())
    request = _request({"task_instructions": "Do something."})

    await runner.execute(request, emitter, is_cancelled=never_cancelled)

    assert len(emitter.errors) == 1
    assert isinstance(emitter.errors[0], RuntimeError)
    assert emitter.finals == []


async def test_on_start_called_once_before_loop():
    emitter = FakeEmitter()
    fake_loop = FakeLoop()
    runner = _runner(loop=fake_loop)
    request = _request({"task_instructions": "Check this."})

    await runner.execute(request, emitter, is_cancelled=never_cancelled)

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

    await runner.execute(request, emitter, is_cancelled=never_cancelled)

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

    await runner.execute(request, emitter, is_cancelled=never_cancelled)

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

    await runner.execute(request, emitter, is_cancelled=never_cancelled)

    assert len(emitter.errors) == 1
    assert isinstance(emitter.errors[0], SchemaValidationError)
    assert emitter.finals == []


async def test_no_output_schema_uses_single_plain_loop():
    """No output_schema → plain loop only, no enforcer, on_final with canned result."""
    emitter = FakeEmitter()
    fake_loop = FakeLoop()
    runner = _runner(loop=fake_loop)
    request = _request({"task_instructions": "Plain task"})

    await runner.execute(request, emitter, is_cancelled=never_cancelled)

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


@pytest.mark.parametrize(
    ("stop_reason", "error"),
    [("llm_error", "rate limited"), ("timeout", "execution exceeded 60s")],
)
async def test_failed_main_loop_is_reported_without_enforcing_the_schema(stop_reason, error):
    emitter = FakeEmitter()
    schema = {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]}
    loop = FailureLoop(stop_reason=stop_reason, error=error)
    runner = _runner(resolver=FakeResolverWithTools(), loop=loop)

    await runner.execute(_request({"task_instructions": "Do X", "output_schema": schema}), emitter, is_cancelled=never_cancelled)

    assert [str(raised) for raised in emitter.errors] == [error]
    assert emitter.finals == []
    assert loop.call_count == 1


# ---------------------------------------------------------------------------
# Tests: agent.schema_max_retries overrides / falls back to settings
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("agent_schema_max_retries", "expected_attempts"),
    [(0, 1), (None, 3)],
    ids=["agent-setting-wins-even-when-zero", "falls-back-to-service-setting"],
)
async def test_schema_retries_come_from_the_agent_then_the_service_setting(
    agent_schema_max_retries, expected_attempts
):
    emitter = FakeEmitter()
    schema = {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]}
    # The LLM never calls the answer tool, so every allowed attempt is used.
    answer_loop = AnswerToolLoop([(None, TokenUsage())] * 5)
    runner = _runner(loop=answer_loop)
    agent = _agent_spec(schema_max_retries=agent_schema_max_retries)

    await runner.execute(_request({"task_instructions": "Do X", "output_schema": schema}, agents=[agent]), emitter, is_cancelled=never_cancelled)

    assert answer_loop.call_count == expected_attempts
    assert isinstance(emitter.errors[0], SchemaValidationError)


# ---------------------------------------------------------------------------
# Tests: tools + output_schema when the main loop's final text already matches
# ---------------------------------------------------------------------------


class FinalTextThenAnswerLoop(AgentLoop):
    """First run() returns ``final_text``; later runs answer via ANSWER_TOOL."""

    def __init__(
        self, final_text: str | None, answer_args: dict, stop_reason: str = "completed"
    ) -> None:
        self._final_text = final_text
        self._answer_args = answer_args
        self._stop_reason = stop_reason
        self.call_count = 0

    async def run(self, context, tools, emitter, stop) -> LoopResult:
        self.call_count += 1
        if self.call_count == 1:
            return LoopResult(
                final_text=self._final_text,
                tool_invocations=1,
                iterations=2,
                stop_reason=self._stop_reason,
                token_usage=TokenUsage(prompt_tokens=5, completion_tokens=2, total_tokens=7),
            )
        await tools.execute(ANSWER_TOOL, self._answer_args)
        return LoopResult(
            final_text=None,
            tool_invocations=1,
            iterations=1,
            stop_reason="completed",
            token_usage=TokenUsage(prompt_tokens=3, completion_tokens=1, total_tokens=4),
        )


Y_SCHEMA = {"type": "object", "properties": {"y": {"type": "integer"}}, "required": ["y"]}


@pytest.mark.parametrize(
    ("schema", "final_text", "expected"),
    [
        (Y_SCHEMA, '{"y": 42}', {"y": 42}),
        ({"type": "array", "items": {"type": "string"}}, '["a", "b"]', ["a", "b"]),
    ],
    ids=["object", "non-object-schema"],
)
async def test_final_text_already_matching_the_schema_skips_enforcement(schema, final_text, expected):
    emitter = FakeEmitter()
    loop = FinalTextThenAnswerLoop(final_text, answer_args={"y": 7})
    runner = _runner(resolver=FakeResolverWithTools(), loop=loop)

    await runner.execute(_request({"task_instructions": "Do Y", "output_schema": schema}), emitter, is_cancelled=never_cancelled)

    assert emitter.errors == []
    final = emitter.finals[0]
    assert loop.call_count == 1
    assert final.structured_output == expected
    assert json.loads(final.final_text) == expected
    assert final.stop_reason == "schema_satisfied"
    assert (final.iterations, final.tool_invocations, final.token_usage.total_tokens) == (2, 1, 7)


@pytest.mark.parametrize(
    "final_text",
    [None, "", "The answer is 42.", '```json\n{"y": 42}\n```', '{"y": "forty-two"}', "{}"],
    ids=["none", "empty", "prose", "fenced-json", "wrong-type", "missing-required"],
)
async def test_final_text_not_matching_the_schema_is_enforced(final_text):
    emitter = FakeEmitter()
    loop = FinalTextThenAnswerLoop(final_text, answer_args={"y": 7})
    runner = _runner(resolver=FakeResolverWithTools(), loop=loop)

    await runner.execute(_request({"task_instructions": "Do Y", "output_schema": Y_SCHEMA}), emitter, is_cancelled=never_cancelled)

    assert emitter.errors == []
    final = emitter.finals[0]
    assert loop.call_count == 2
    assert final.structured_output == {"y": 7}
    assert (final.iterations, final.tool_invocations, final.token_usage.total_tokens) == (3, 2, 11)


async def test_final_text_left_over_from_an_unfinished_tool_loop_is_enforced():
    emitter = FakeEmitter()
    loop = FinalTextThenAnswerLoop('{"y": 42}', answer_args={"y": 7}, stop_reason="max_iter_reached")
    runner = _runner(resolver=FakeResolverWithTools(), loop=loop)

    await runner.execute(_request({"task_instructions": "Do Y", "output_schema": Y_SCHEMA}), emitter, is_cancelled=never_cancelled)

    assert emitter.errors == []
    assert loop.call_count == 2
    assert emitter.finals[0].structured_output == {"y": 7}


# ---------------------------------------------------------------------------
# Tests: logging redaction
# ---------------------------------------------------------------------------


async def test_instructions_and_messages_redaction_in_logs():
    secret_marker = "SUPER_SECRET_API_KEY_12345"
    emitter = FakeEmitter()
    runner = _runner()
    request = _request({"task_instructions": f"Process this: {secret_marker}"})

    with capture_logs_at("DEBUG") as logs:
        await runner.execute(request, emitter, is_cancelled=never_cancelled)

    instructions_line = log_line_starting_with(logs, "task instructions=")
    assert secret_marker not in instructions_line
    assert "<redacted" in instructions_line

    messages_line = log_line_starting_with(logs, "prompt messages")
    assert secret_marker not in messages_line
    assert "<redacted" in messages_line


async def test_final_text_redaction_in_logs():
    secret_output = "SENSITIVE_ANSWER_OUTPUT_789"
    emitter = FakeEmitter()

    class SecretResultLoop(AgentLoop):
        async def run(self, context, tools, emitter, stop) -> LoopResult:
            return LoopResult(
                final_text=secret_output,
                tool_invocations=0,
                iterations=1,
                stop_reason="completed",
            )

    runner = _runner(loop=SecretResultLoop())
    request = _request({"task_instructions": "Do something"})

    with capture_logs_at("DEBUG") as logs:
        await runner.execute(request, emitter, is_cancelled=never_cancelled)

    log_text = "\n".join(logs)
    assert secret_output not in log_text
    assert "final_text" in log_text
    assert "<redacted" in log_text


# ---------------------------------------------------------------------------
# Tests: output_schema logging
# ---------------------------------------------------------------------------


async def test_single_task_redacts_output_schema_descriptions():
    """Only the schema's property names may be logged; descriptions can carry PII."""
    schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "User's full name — PII"},
            "age": {"type": "integer", "description": "SENSITIVE_MARKER_12345"},
        },
        "required": ["name", "age"],
    }

    emitter = FakeEmitter()
    runner = _runner()
    request = _request({"task_instructions": "Extract data", "output_schema": schema})

    with capture_logs_at("DEBUG") as messages:
        await runner.execute(request, emitter, is_cancelled=never_cancelled)

    log_output = "".join(messages)
    assert "SENSITIVE_MARKER_12345" not in log_output
    assert "PII" not in log_output

    output_schema_line = log_line_starting_with(messages, "output_schema=")
    assert "age" in output_schema_line
    assert "name" in output_schema_line


@pytest.mark.parametrize(
    ("output_schema", "expected_line"),
    [
        ({"type": "object", "properties": None}, "output_schema=[]"),
        ({"type": "object"}, "output_schema=[]"),
        ({"type": "object", "properties": "not-a-mapping"}, "output_schema=[]"),
    ],
    ids=["properties_is_null", "properties_missing", "properties_not_a_mapping"],
)
async def test_output_schema_log_survives_a_schema_without_usable_properties(
    output_schema, expected_line
):
    """output_schema is unvalidated JSON; logging it must never fail the request."""
    emitter = FakeEmitter()
    runner = _runner()
    request = _request({"task_instructions": "Extract data", "output_schema": output_schema})

    with capture_logs_at("DEBUG") as messages:
        await runner.execute(request, emitter, is_cancelled=never_cancelled)

    assert log_line_starting_with(messages, "output_schema=") == expected_line


async def test_output_schema_log_digests_a_schema_that_is_not_a_dict():
    """A non-dict output_schema is digested instead of crashing the log call."""
    secret_marker = "SCHEMA_AS_STRING_SECRET_42"
    emitter = FakeEmitter()
    runner = _runner()
    request = _request({"task_instructions": "Extract data", "output_schema": secret_marker})

    with capture_logs_at("DEBUG") as messages:
        await runner.execute(request, emitter, is_cancelled=never_cancelled)

    output_schema_line = log_line_starting_with(messages, "output_schema=")
    assert "<redacted" in output_schema_line
    assert secret_marker not in output_schema_line
