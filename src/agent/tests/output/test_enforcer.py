"""Tests for StructuredOutputEnforcer.

Uses a scripted FakeAgentLoop that, on each run() call, pops a behaviour from
a queue: it may call the registered ANSWER_TOOL with given args (simulating the
LLM calling the tool), or do nothing (simulating the LLM not calling the tool).
"""

from __future__ import annotations

import pytest
from app.emitters.base import Emitter
from app.exceptions import (
    AgentServiceError,
    InvalidOutputSchemaError,
    SchemaValidationError,
)
from app.llm.client import LLMChunk, ToolCallFragment
from app.loop.agent_loop import AgentLoop, DefaultAgentLoop
from app.loop.context import AgentContext
from app.loop.stop_policy import StopPolicy
from app.output.enforcer import StructuredOutputEnforcer
from app.tools.registry import ToolRegistry
from app.tools.system_tools.structured_output import ANSWER_TOOL
from shared.models.agent_service import AgentSpec, LoopResult, TokenUsage, ToolResult
from shared.models.ai_providers import LLMConfigData, LLMData
from tests.cancellation import never_cancelled
from tests.log_capture import log_line_starting_with, capture_logs_at
from tests.loop.test_default_agent_loop import FakeLLMClient, text_chunks
from tests.secret_sealing import agent_cryptographer

# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class FakeEmitter(Emitter):
    async def on_start(self, request) -> None:
        pass

    async def on_chunk(self, chunk: LLMChunk) -> None:
        pass

    async def on_tool_call(self, call: object) -> None:
        pass

    async def on_tool_result(self, result: ToolResult) -> None:
        pass

    async def on_warning(self, message: str) -> None:
        pass

    async def on_final(self, result: LoopResult) -> None:
        pass

    async def on_error(self, error: Exception) -> None:
        pass


class ScriptedLoop(AgentLoop):
    """On each run() call pops a (args_or_none, token_usage) pair.

    If args_or_none is not None, it calls the ANSWER_TOOL executor with those
    args (simulating the LLM choosing to use the tool).  If None, it skips the
    tool call (simulating the LLM ignoring the tool).
    """

    def __init__(self, script: list[tuple[dict | None, TokenUsage]]) -> None:
        self._script = list(script)

    async def run(
        self,
        context: AgentContext,
        tools: ToolRegistry,
        emitter: Emitter,
        stop: StopPolicy,
    ) -> LoopResult:
        args, token_usage = self._script.pop(0)

        if args is not None:
            await tools.execute(ANSWER_TOOL, args)

        return LoopResult(
            final_text=None,
            tool_invocations=1 if args is not None else 0,
            iterations=1,
            stop_reason="completed",
            token_usage=token_usage,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_agent_spec() -> AgentSpec:
    return AgentSpec(
        id=1,
        name="test-agent",
        instructions="You are a test assistant.",
        llm=LLMData(provider="openai", config=LLMConfigData(model="gpt-4o")),
    )


def _make_context() -> AgentContext:
    return AgentContext(
        agent=_make_agent_spec(),
        attachments=[],
        correlation_id="test-corr",
        is_cancelled=never_cancelled,
    )


OBJECT_SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
}

STRING_SCHEMA = {"type": "string"}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_valid_on_first_attempt_returns_parsed():
    usage = TokenUsage(prompt_tokens=5, completion_tokens=3, total_tokens=8)
    loop = ScriptedLoop([({"answer": "hello"}, usage)])
    enforcer = StructuredOutputEnforcer(loop, max_retries=2)
    context = _make_context()

    result = await enforcer.enforce(context, OBJECT_SCHEMA, FakeEmitter())

    assert result.parsed == {"answer": "hello"}
    assert result.token_usage == usage
    assert result.iterations == 1
    assert result.tool_invocations == 1
    assert context.tool_choice is None


async def test_tool_choice_is_reset_to_none_on_success():
    loop = ScriptedLoop([({"answer": "hi"}, TokenUsage())])
    enforcer = StructuredOutputEnforcer(loop, max_retries=2)
    context = _make_context()

    await enforcer.enforce(context, OBJECT_SCHEMA, FakeEmitter())

    assert context.tool_choice is None


async def test_invalid_then_valid_uses_second_attempt():
    usage1 = TokenUsage(prompt_tokens=4, completion_tokens=2, total_tokens=6)
    usage2 = TokenUsage(prompt_tokens=6, completion_tokens=3, total_tokens=9)
    loop = ScriptedLoop(
        [
            ({"answer": 99}, usage1),  # answer is int, not string → invalid
            ({"answer": "ok"}, usage2),
        ]
    )
    enforcer = StructuredOutputEnforcer(loop, max_retries=2)
    context = _make_context()

    result = await enforcer.enforce(context, OBJECT_SCHEMA, FakeEmitter())

    assert result.parsed == {"answer": "ok"}
    assert result.token_usage.prompt_tokens == 10
    assert result.token_usage.completion_tokens == 5
    assert result.token_usage.total_tokens == 15
    assert result.iterations == 2
    assert result.tool_invocations == 2


async def test_schema_enforce_debug_log_redacts_the_validation_error():
    secret_marker = "SENSITIVE_ANSWER_VALUE_24680"
    schema = {
        "type": "object",
        "properties": {"answer": {"type": "integer"}},
        "required": ["answer"],
    }
    loop = ScriptedLoop(
        [
            ({"answer": secret_marker}, TokenUsage()),
            ({"answer": 1}, TokenUsage()),
        ]
    )
    enforcer = StructuredOutputEnforcer(loop, max_retries=2)
    context = _make_context()

    with capture_logs_at("DEBUG") as logs:
        await enforcer.enforce(context, schema, FakeEmitter())

    log_line = log_line_starting_with(logs, "schema_enforce attempt=0")
    assert secret_marker not in log_line
    assert "<redacted" in log_line


async def test_usage_is_summed_across_attempts():
    u = TokenUsage(prompt_tokens=3, completion_tokens=1, total_tokens=4)
    loop = ScriptedLoop(
        [
            ({"answer": 1}, u),  # invalid
            ({"answer": "x"}, u),  # valid
        ]
    )
    enforcer = StructuredOutputEnforcer(loop, max_retries=2)
    context = _make_context()

    result = await enforcer.enforce(context, OBJECT_SCHEMA, FakeEmitter())

    assert result.token_usage.prompt_tokens == 6
    assert result.token_usage.completion_tokens == 2
    assert result.token_usage.total_tokens == 8


async def test_iterations_and_tool_invocations_summed_across_attempts():
    """Every enforcer turn's iterations/tool_invocations are aggregated,
    not discarded — including a turn where the tool was never called."""
    u = TokenUsage()
    loop = ScriptedLoop(
        [
            (None, u),  # tool not called → iterations+=1, tool_invocations+=0
            ({"answer": 1}, u),  # invalid → iterations+=1, tool_invocations+=1
            ({"answer": "ok"}, u),  # valid → iterations+=1, tool_invocations+=1
        ]
    )
    enforcer = StructuredOutputEnforcer(loop, max_retries=2)
    context = _make_context()

    result = await enforcer.enforce(context, OBJECT_SCHEMA, FakeEmitter())

    assert result.parsed == {"answer": "ok"}
    assert result.iterations == 3
    assert result.tool_invocations == 2


async def test_capture_never_set_raises_schema_validation_error():
    """Loop never calls the tool → SchemaValidationError after retries exhausted."""
    loop = ScriptedLoop(
        [
            (None, TokenUsage()),
            (None, TokenUsage()),
            (None, TokenUsage()),
        ]
    )
    enforcer = StructuredOutputEnforcer(loop, max_retries=2)
    context = _make_context()

    with pytest.raises(SchemaValidationError):
        await enforcer.enforce(context, OBJECT_SCHEMA, FakeEmitter())


async def test_exhausted_invalid_raises_schema_validation_error():
    """All attempts return invalid data → SchemaValidationError."""
    loop = ScriptedLoop(
        [
            ({"answer": 1}, TokenUsage()),
            ({"answer": 2}, TokenUsage()),
            ({"answer": 3}, TokenUsage()),
        ]
    )
    enforcer = StructuredOutputEnforcer(loop, max_retries=2)
    context = _make_context()

    with pytest.raises(SchemaValidationError):
        await enforcer.enforce(context, OBJECT_SCHEMA, FakeEmitter())


async def test_tool_choice_reset_on_failure():
    """tool_choice is reset to None even when enforcement fails."""
    loop = ScriptedLoop(
        [
            (None, TokenUsage()),
            (None, TokenUsage()),
            (None, TokenUsage()),
        ]
    )
    enforcer = StructuredOutputEnforcer(loop, max_retries=2)
    context = _make_context()

    with pytest.raises(SchemaValidationError):
        await enforcer.enforce(context, OBJECT_SCHEMA, FakeEmitter())

    assert context.tool_choice is None


async def test_wrapped_non_object_schema_returns_unwrapped_value():
    """For a non-object schema, the LLM provides {result: value}; enforcer unwraps it."""
    inner_value = "the final string answer"
    loop = ScriptedLoop([({"result": inner_value}, TokenUsage())])
    enforcer = StructuredOutputEnforcer(loop, max_retries=2)
    context = _make_context()

    result = await enforcer.enforce(context, STRING_SCHEMA, FakeEmitter())

    assert result.parsed == inner_value


async def test_corrective_message_appended_on_no_capture():
    """When tool not called, a corrective user message is appended before next attempt."""
    loop = ScriptedLoop(
        [
            (None, TokenUsage()),
            ({"answer": "ok"}, TokenUsage()),
        ]
    )
    enforcer = StructuredOutputEnforcer(loop, max_retries=2)
    context = _make_context()

    await enforcer.enforce(context, OBJECT_SCHEMA, FakeEmitter())

    user_messages = [m for m in context.messages if m.get("role") == "user"]
    assert len(user_messages) >= 2
    assert "submit_final_answer" in user_messages[1]["content"].lower()


# ---------------------------------------------------------------------------
# Tests: loop failure during schema enforcement
# ---------------------------------------------------------------------------


class FailingLoop(AgentLoop):
    """Returns a failure LoopResult without calling the answer tool.

    Tracks how many times run() was called.
    """

    def __init__(self, stop_reason: str, error: str | None) -> None:
        self._stop_reason = stop_reason
        self._error = error
        self.call_count = 0

    async def run(
        self,
        context: AgentContext,
        tools: ToolRegistry,
        emitter,
        stop: StopPolicy,
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


async def test_llm_error_during_enforcement_raises_agent_service_error():
    """Loop returns llm_error → AgentServiceError with the original message, not SchemaValidationError."""
    loop = FailingLoop(stop_reason="llm_error", error="boom")
    enforcer = StructuredOutputEnforcer(loop, max_retries=2)
    context = _make_context()

    with pytest.raises(AgentServiceError) as exc_info:
        await enforcer.enforce(context, OBJECT_SCHEMA, FakeEmitter())

    assert "boom" in str(exc_info.value)
    assert not isinstance(exc_info.value, SchemaValidationError)
    assert loop.call_count == 1
    assert context.tool_choice is None


async def test_timeout_during_enforcement_raises_agent_service_error():
    """Loop returns timeout → AgentServiceError, not SchemaValidationError."""
    loop = FailingLoop(stop_reason="timeout", error="execution exceeded 30s")
    enforcer = StructuredOutputEnforcer(loop, max_retries=2)
    context = _make_context()

    with pytest.raises(AgentServiceError) as exc_info:
        await enforcer.enforce(context, OBJECT_SCHEMA, FakeEmitter())

    assert "execution exceeded 30s" in str(exc_info.value)
    assert not isinstance(exc_info.value, SchemaValidationError)
    assert loop.call_count == 1
    assert context.tool_choice is None


async def test_failure_stop_reason_with_no_error_message_uses_fallback():
    """When error field is None, a fallback message is constructed from stop_reason."""
    loop = FailingLoop(stop_reason="llm_error", error=None)
    enforcer = StructuredOutputEnforcer(loop, max_retries=2)
    context = _make_context()

    with pytest.raises(AgentServiceError) as exc_info:
        await enforcer.enforce(context, OBJECT_SCHEMA, FakeEmitter())

    assert "llm_error" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Tests: invalid output_schema fails fast, no LLM calls, no retry
# ---------------------------------------------------------------------------


BARE_FIELD_MAP_SCHEMA = {"reasoning": {"type": "string", "description": "why"}}


async def test_bare_field_map_schema_raises_before_any_llm_call():
    """A bare field map has no top-level 'type' — enforce() must reject it
    without ever calling the loop, since the schema is known upfront."""
    loop = FailingLoop(stop_reason="llm_error", error="should never run")
    enforcer = StructuredOutputEnforcer(loop, max_retries=2)
    context = _make_context()

    with pytest.raises(InvalidOutputSchemaError):
        await enforcer.enforce(context, BARE_FIELD_MAP_SCHEMA, FakeEmitter())

    assert loop.call_count == 0


async def test_invalid_output_schema_is_not_retried():
    """InvalidOutputSchemaError is raised once, not wrapped as SchemaValidationError
    and not retried across max_retries attempts."""
    loop = FailingLoop(stop_reason="llm_error", error="should never run")
    enforcer = StructuredOutputEnforcer(loop, max_retries=3)
    context = _make_context()

    with pytest.raises(InvalidOutputSchemaError) as exc_info:
        await enforcer.enforce(context, BARE_FIELD_MAP_SCHEMA, FakeEmitter())

    assert not isinstance(exc_info.value, SchemaValidationError)
    assert loop.call_count == 0


# ---------------------------------------------------------------------------
# Tests: wrapped schema — missing or malformed "result" key
# ---------------------------------------------------------------------------


async def test_wrapped_missing_or_malformed_arguments_retry_instead_of_crashing():
    """When wrapped=True and LLM returns dict without "result" key or non-dict,
    enforcer should retry instead of crashing with KeyError."""
    usage = TokenUsage()
    loop = ScriptedLoop(
        [
            ({"answr": "x"}, usage),  # dict but missing "result" key → invalid
            ({"result": "ok"}, usage),  # valid with "result" key
        ]
    )
    enforcer = StructuredOutputEnforcer(loop, max_retries=2)
    context = _make_context()

    result = await enforcer.enforce(context, STRING_SCHEMA, FakeEmitter())

    assert result.parsed == "ok"


async def test_wrapped_non_dict_arguments_retry_instead_of_crashing():
    """When wrapped=True and LLM returns non-dict (e.g. list),
    enforcer should retry instead of crashing."""
    usage = TokenUsage()
    loop = ScriptedLoop(
        [
            (["not", "a", "dict"], usage),  # non-dict → invalid
            ({"result": "ok"}, usage),  # valid
        ]
    )
    enforcer = StructuredOutputEnforcer(loop, max_retries=2)
    context = _make_context()

    result = await enforcer.enforce(context, STRING_SCHEMA, FakeEmitter())

    assert result.parsed == "ok"


async def test_missing_result_key_is_not_accepted_as_a_null_answer():
    """When wrapped=True and dict lacks "result" key, it should NOT be accepted
    as a null answer even if the schema allows null. _MISSING is distinct from None."""
    usage = TokenUsage()
    nullable_schema = {"type": ["string", "null"]}
    loop = ScriptedLoop(
        [
            ({}, usage),  # empty dict, no "result" key → should NOT match null
            ({"result": "done"}, usage),  # valid
        ]
    )
    enforcer = StructuredOutputEnforcer(loop, max_retries=2)
    context = _make_context()

    result = await enforcer.enforce(context, nullable_schema, FakeEmitter())

    assert result.parsed == "done"
    assert result.iterations == 2


async def test_missing_result_key_exhausts_retries_as_schema_validation_error():
    """When wrapped=True and all attempts return dict without "result" key,
    enforcer should exhaust retries and raise SchemaValidationError."""
    usage = TokenUsage()
    loop = ScriptedLoop(
        [
            ({}, usage),  # missing "result" key
            ({}, usage),  # missing "result" key
            ({}, usage),  # missing "result" key
        ]
    )
    enforcer = StructuredOutputEnforcer(loop, max_retries=2)
    context = _make_context()

    with pytest.raises(SchemaValidationError):
        await enforcer.enforce(context, STRING_SCHEMA, FakeEmitter())


# ---------------------------------------------------------------------------
# Tests: the model calls schema fields as if they were tools (real loop)
# ---------------------------------------------------------------------------


EMAIL_SCHEMA = {
    "type": "object",
    "properties": {"initial_email": {"type": "string"}, "status": {"type": "string"}},
    "required": ["initial_email", "status"],
}

LIST_OF_TITLES_SCHEMA = {
    "type": "array",
    "items": {"type": "object", "properties": {"title": {"type": "string"}}},
}


def _tool_calls_response(*calls: tuple[str, str, str]) -> list[LLMChunk]:
    chunks = [
        LLMChunk(tool_call_fragment=ToolCallFragment(id=call_id, name=name, arguments_delta=args))
        for call_id, name, args in calls
    ]
    chunks.append(LLMChunk(finish_reason="tool_calls"))
    return chunks


def _tool_results(context: AgentContext) -> dict[str, str]:
    return {
        message["tool_call_id"]: message["content"]
        for message in context.messages
        if message.get("role") == "tool"
    }


def _field_explanation(name: str) -> str:
    return (
        f"'{name}' is not a tool: it is a field of the {ANSWER_TOOL} arguments. "
        f"Call {ANSWER_TOOL} once, with all fields in its arguments."
    )


async def test_field_called_as_tool_gets_explanation_and_unknown_name_keeps_generic_error():
    llm = FakeLLMClient(
        [
            _tool_calls_response(
                ("call-email", "initial_email", '{"value": "Hi"}'),
                ("call-search", "web_search", "{}"),
                ("call-status", "status", "{}"),
            ),
            _tool_calls_response(
                ("call-answer", ANSWER_TOOL, '{"initial_email": "Hi", "status": "sent"}')
            ),
        ]
    )
    enforcer = StructuredOutputEnforcer(DefaultAgentLoop(llm, agent_cryptographer()), max_retries=2)
    context = _make_context()

    result = await enforcer.enforce(context, EMAIL_SCHEMA, FakeEmitter())

    tool_results = _tool_results(context)
    assert _field_explanation("initial_email") in tool_results["call-email"]
    assert _field_explanation("status") in tool_results["call-status"]
    assert "Unknown tool: web_search" in tool_results["call-search"]
    assert result.parsed == {"initial_email": "Hi", "status": "sent"}
    assert [tool.name for tool in llm.received_tools[0]] == [ANSWER_TOOL]


async def test_corrective_message_names_fields_called_as_tools_when_no_answer_captured():
    llm = FakeLLMClient(
        [
            _tool_calls_response(
                ("call-email", "initial_email", "{}"), ("call-status", "status", "{}")
            ),
            _tool_calls_response(
                ("call-answer", ANSWER_TOOL, '{"initial_email": "Hi", "status": "sent"}')
            ),
        ]
    )
    enforcer = StructuredOutputEnforcer(DefaultAgentLoop(llm, agent_cryptographer()), max_retries=2)
    context = _make_context()

    await enforcer.enforce(context, EMAIL_SCHEMA, FakeEmitter())

    user_messages = [m["content"] for m in context.messages if m.get("role") == "user"]
    assert user_messages[-1] == (
        f"You called initial_email, status as tools, but they are fields of the {ANSWER_TOOL} "
        f"arguments, not tools. Call {ANSWER_TOOL} once, with all fields in its arguments, "
        "matching the required schema."
    )


async def test_corrective_message_without_field_calls_is_unchanged():
    llm = FakeLLMClient(
        [
            _tool_calls_response(("call-search", "web_search", "{}")),
            _tool_calls_response(
                ("call-answer", ANSWER_TOOL, '{"initial_email": "Hi", "status": "sent"}')
            ),
        ]
    )
    enforcer = StructuredOutputEnforcer(DefaultAgentLoop(llm, agent_cryptographer()), max_retries=2)
    context = _make_context()

    await enforcer.enforce(context, EMAIL_SCHEMA, FakeEmitter())

    user_messages = [m["content"] for m in context.messages if m.get("role") == "user"]
    assert user_messages[-1] == (
        "You must call submit_final_answer. "
        "Call submit_final_answer with your final answer matching the required schema."
    )


_TEXT_ONLY_CORRECTIVE = (
    f"You must call {ANSWER_TOOL}. "
    f"Call {ANSWER_TOOL} with your final answer matching the required schema."
)


async def test_text_only_attempt_after_field_calls_does_not_repeat_the_field_complaint():
    llm = FakeLLMClient(
        [
            _tool_calls_response(("call-email", "initial_email", "{}")),
            text_chunks("plain text"),
            _tool_calls_response(
                ("call-answer", ANSWER_TOOL, '{"initial_email": "Hi", "status": "sent"}')
            ),
        ]
    )
    enforcer = StructuredOutputEnforcer(DefaultAgentLoop(llm, agent_cryptographer()), max_retries=2)
    context = _make_context()

    await enforcer.enforce(context, EMAIL_SCHEMA, FakeEmitter())

    user_messages = [m["content"] for m in context.messages if m.get("role") == "user"]
    assert user_messages[-1] == _TEXT_ONLY_CORRECTIVE


async def test_repeated_text_only_attempts_do_not_stack_the_corrective_prefix():
    llm = FakeLLMClient(
        [
            text_chunks("first"),
            text_chunks("second"),
            text_chunks("third"),
            _tool_calls_response(
                ("call-answer", ANSWER_TOOL, '{"initial_email": "Hi", "status": "sent"}')
            ),
        ]
    )
    enforcer = StructuredOutputEnforcer(DefaultAgentLoop(llm, agent_cryptographer()), max_retries=3)
    context = _make_context()

    await enforcer.enforce(context, EMAIL_SCHEMA, FakeEmitter())

    user_messages = [m["content"] for m in context.messages if m.get("role") == "user"]
    assert user_messages[-3:] == [_TEXT_ONLY_CORRECTIVE] * 3


async def test_wrapped_schema_counts_only_result_as_a_field():
    llm = FakeLLMClient(
        [
            _tool_calls_response(("call-result", "result", "{}"), ("call-title", "title", "{}")),
            _tool_calls_response(("call-answer", ANSWER_TOOL, '{"result": [{"title": "A"}]}')),
        ]
    )
    enforcer = StructuredOutputEnforcer(DefaultAgentLoop(llm, agent_cryptographer()), max_retries=2)
    context = _make_context()

    result = await enforcer.enforce(context, LIST_OF_TITLES_SCHEMA, FakeEmitter())

    tool_results = _tool_results(context)
    assert _field_explanation("result") in tool_results["call-result"]
    assert "Unknown tool: title" in tool_results["call-title"]
    assert result.parsed == [{"title": "A"}]
