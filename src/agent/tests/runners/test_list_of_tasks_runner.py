"""
Tests for ListOfTasksRunner.

Reuses the lightweight fakes defined for SingleTaskRunner's tests where
possible; otherwise defines minimal task-list-specific fakes.
"""

from __future__ import annotations

import json

import pytest

from app.emitters.base import Emitter
from app.exceptions import AgentServiceError
from app.llm.client import LLMChunk
from app.loop.agent_loop import AgentLoop
from app.loop.context import AgentContext
from app.resources.resolver import AgentResolver, ResolvedAgent
from app.runners.deps import RunnerDependencies
from app.runners.list_of_tasks import ListOfTasksRunner, format_context_preamble
from app.tools.registry import ToolRegistry
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
        self.task_starts: list[tuple[str, int]] = []

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

    async def on_task_start(self, task_name: str, task_order: int) -> None:
        self.task_starts.append((task_name, task_order))


class ScriptedLoop(AgentLoop):
    """Returns one scripted LoopResult per call, keyed by call order.

    Also records the ``context.messages`` snapshot at call time so tests can
    assert what a task saw (e.g. injected context from a previous task).
    """

    def __init__(self, results: list[LoopResult]) -> None:
        self._results = list(results)
        self.received_messages: list[list[dict]] = []
        self.call_count = 0

    async def run(self, context, tools, emitter, stop) -> LoopResult:
        self.received_messages.append(list(context.messages))
        self.call_count += 1
        return self._results.pop(0)


class FakeResolver:
    """Returns a ResolvedAgent with an empty ToolRegistry (resolved once)."""

    def __init__(self) -> None:
        self.resolve_calls = 0

    async def resolve(self, agent: AgentSpec, request: AgentRequest) -> ResolvedAgent:
        self.resolve_calls += 1
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _agent_spec() -> AgentSpec:
    return AgentSpec(
        id=12,
        name="researcher",
        instructions="You research topics thoroughly.",
        llm=LLMData(provider="openai", config=LLMConfigData(model="gpt-4o")),
        max_iter=5,
    )


def _request(tasks: list[dict], agents: list[AgentSpec] | None = None) -> AgentRequest:
    return AgentRequest(
        correlation_id="test-corr",
        run_type=RunType.LIST_OF_TASKS,
        agents=agents if agents is not None else [_agent_spec()],
        payload={"tasks": tasks},
    )


def _runner(resolver=None, loop=None) -> ListOfTasksRunner:
    resolver = resolver or FakeResolver()
    loop = loop or ScriptedLoop([])
    deps = RunnerDependencies(resolver=resolver, loop=loop)
    return ListOfTasksRunner(deps)


def _result(text: str, stop_reason: str = "completed", **overrides) -> LoopResult:
    defaults = dict(
        final_text=text,
        tool_invocations=0,
        iterations=1,
        stop_reason=stop_reason,
        token_usage=TokenUsage(),
    )
    defaults.update(overrides)
    return LoopResult(**defaults)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_two_tasks_run_sequentially_in_order():
    emitter = FakeEmitter()
    loop = ScriptedLoop([_result("A done"), _result("B done")])
    runner = _runner(loop=loop)
    request = _request(
        [
            {"name": "task_a", "instructions": "Do A"},
            {"name": "task_b", "instructions": "Do B"},
        ]
    )

    await runner.execute(request, emitter)

    assert emitter.errors == []
    assert len(emitter.finals) == 1
    assert loop.call_count == 2
    assert emitter.task_starts == [("task_a", 0), ("task_b", 1)]


async def test_context_injection_prepends_prior_task_output():
    emitter = FakeEmitter()
    loop = ScriptedLoop([_result("A's answer"), _result("B done")])
    runner = _runner(loop=loop)
    request = _request(
        [
            {"name": "task_a", "instructions": "Do A"},
            {"name": "task_b", "instructions": "Do B", "context": ["task_a"]},
        ]
    )

    await runner.execute(request, emitter)

    assert emitter.errors == []
    task_b_messages = loop.received_messages[1]
    user_message = next(m for m in task_b_messages if m["role"] == "user")
    assert "PREVIOUS TASKS OUTPUTS" in user_message["content"]
    assert "Task 'task_a':" in user_message["content"]
    assert "A's answer" in user_message["content"]
    assert "Do B" in user_message["content"]


async def test_missing_named_context_calls_on_error():
    emitter = FakeEmitter()
    loop = ScriptedLoop([_result("A done"), _result("B done")])
    runner = _runner(loop=loop)
    request = _request(
        [
            {"name": "task_a", "instructions": "Do A"},
            {"name": "task_b", "instructions": "Do B", "context": ["unknown_task"]},
        ]
    )

    await runner.execute(request, emitter)

    assert len(emitter.errors) == 1
    assert isinstance(emitter.errors[0], AgentServiceError)
    assert emitter.finals == []
    # task_a ran, task_b never invoked the loop because context resolution failed first
    assert loop.call_count == 1


async def test_per_task_output_schema_uses_enforcer():
    from app.tools.system_tools.structured_output import ANSWER_TOOL

    class AnswerToolLoop(AgentLoop):
        def __init__(self, script):
            self._script = list(script)
            self.call_count = 0

        async def run(self, context, tools, emitter, stop) -> LoopResult:
            self.call_count += 1
            args, usage = self._script.pop(0)

            if args is not None and ANSWER_TOOL in {s.name for s in tools.tool_specs()}:
                await tools.execute(ANSWER_TOOL, args)

            return LoopResult(
                final_text="plain text" if args is None else None,
                tool_invocations=1 if args is not None else 0,
                iterations=1,
                stop_reason="completed",
                token_usage=usage,
            )

    schema = {
        "type": "object",
        "properties": {"x": {"type": "string"}},
        "required": ["x"],
    }
    answer_loop = AnswerToolLoop([({"x": "result"}, TokenUsage())])
    emitter = FakeEmitter()
    runner = _runner(loop=answer_loop)
    request = _request(
        [{"name": "task_a", "instructions": "Do A", "output_schema": schema}]
    )

    from unittest.mock import patch

    with patch("app.runners.list_of_tasks._schema_max_retries", return_value=2):
        await runner.execute(request, emitter)

    assert emitter.errors == []
    final = emitter.finals[0]
    assert json.loads(final.final_text) == {"x": "result"}
    assert final.stop_reason == "schema_satisfied"


async def test_mid_sequence_failure_stops_run_and_never_runs_next_task():
    emitter = FakeEmitter()
    failure_result = _result(
        None, stop_reason="llm_error", error="rate limited", tool_invocations=0
    )
    loop = ScriptedLoop([failure_result, _result("B done")])
    runner = _runner(loop=loop)
    request = _request(
        [
            {"name": "task_a", "instructions": "Do A"},
            {"name": "task_b", "instructions": "Do B"},
        ]
    )

    await runner.execute(request, emitter)

    assert len(emitter.errors) == 1
    assert isinstance(emitter.errors[0], AgentServiceError)
    assert "task_a" in str(emitter.errors[0])
    assert emitter.finals == []
    assert loop.call_count == 1


async def test_aggregation_sums_usage_and_uses_last_final_text():
    emitter = FakeEmitter()
    usage_a = TokenUsage(prompt_tokens=2, completion_tokens=1, total_tokens=3)
    usage_b = TokenUsage(prompt_tokens=5, completion_tokens=4, total_tokens=9)
    loop = ScriptedLoop(
        [
            _result("A done", iterations=2, tool_invocations=1, token_usage=usage_a),
            _result("B done", iterations=3, tool_invocations=2, token_usage=usage_b),
        ]
    )
    runner = _runner(loop=loop)
    request = _request(
        [
            {"name": "task_a", "instructions": "Do A"},
            {"name": "task_b", "instructions": "Do B"},
        ]
    )

    await runner.execute(request, emitter)

    final = emitter.finals[0]
    assert final.final_text == "B done"
    assert final.iterations == 5
    assert final.tool_invocations == 3
    assert final.token_usage.prompt_tokens == 7
    assert final.token_usage.completion_tokens == 5
    assert final.token_usage.total_tokens == 12


async def test_on_start_called_exactly_once():
    emitter = FakeEmitter()
    loop = ScriptedLoop([_result("A done"), _result("B done")])
    runner = _runner(loop=loop)
    request = _request(
        [
            {"name": "task_a", "instructions": "Do A"},
            {"name": "task_b", "instructions": "Do B"},
        ]
    )

    await runner.execute(request, emitter)

    assert len(emitter.started) == 1
    assert emitter.started[0] is request


async def test_empty_tasks_list_calls_on_error():
    emitter = FakeEmitter()
    runner = _runner()
    request = _request([])

    await runner.execute(request, emitter)

    assert len(emitter.errors) == 1
    assert isinstance(emitter.errors[0], AgentServiceError)
    assert emitter.finals == []


async def test_duplicate_task_names_calls_on_error():
    emitter = FakeEmitter()
    runner = _runner()
    request = _request(
        [
            {"name": "task_a", "instructions": "Do A"},
            {"name": "task_a", "instructions": "Do A again"},
        ]
    )

    await runner.execute(request, emitter)

    assert len(emitter.errors) == 1
    assert isinstance(emitter.errors[0], AgentServiceError)
    assert emitter.finals == []


async def test_on_task_start_fired_once_per_task_with_correct_name_and_order():
    emitter = FakeEmitter()
    loop = ScriptedLoop([_result("A done"), _result("B done"), _result("C done")])
    runner = _runner(loop=loop)
    request = _request(
        [
            {"name": "task_a", "instructions": "Do A"},
            {"name": "task_b", "instructions": "Do B"},
            {"name": "task_c", "instructions": "Do C"},
        ]
    )

    await runner.execute(request, emitter)

    assert emitter.task_starts == [("task_a", 0), ("task_b", 1), ("task_c", 2)]


# ---------------------------------------------------------------------------
# format_context_preamble unit tests
# ---------------------------------------------------------------------------


def test_format_context_preamble_empty_context_returns_empty_string():
    assert format_context_preamble([], {}) == ""


def test_format_context_preamble_raises_on_unknown_name():
    with pytest.raises(AgentServiceError):
        format_context_preamble(["missing"], {})


def test_format_context_preamble_builds_expected_text():
    preamble = format_context_preamble(["a"], {"a": "answer text"})
    assert preamble == (
        "===== PREVIOUS TASKS OUTPUTS =====\n\n"
        "Task 'a':\nanswer text\n\n"
        "===== END PREVIOUS TASKS OUTPUTS =====\n\n"
    )
    assert "===== END PREVIOUS TASKS OUTPUTS =====" in preamble
