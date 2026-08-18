"""
Integration tests for DefaultAgentLoop.

Uses FakeLLMClient (scripted chunk sequences), RecordingEmitter (event log),
and StubToolRegistry (callable-backed tool dispatch) to verify observable
loop behaviour without touching any real I/O.
"""

from __future__ import annotations

import asyncio
import inspect
from typing import AsyncIterator, Callable

import pytest

from app.emitters.base import Emitter
from app.llm.client import LLMChunk, LLMClient, ToolCallFragment
from app.loop.agent_loop import DefaultAgentLoop
from app.loop.context import AgentContext
from app.loop.stop_policy import MaxIterAndNoToolCalls
from app.tools.registry import ToolRegistry, ToolSpec
from shared.models.agent_service import LoopResult, ToolResult
from shared.models.ai_providers import LLMConfigData, LLMData
from shared.models.agent_service import AgentSpec


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class FakeLLMClient(LLMClient):
    """Yields scripted chunk sequences; pops one response per ``chat()`` call.

    Set ``chat_raises`` to an exception instance to make the next ``chat()``
    call raise instead of yielding chunks.
    Records the model_config passed to each ``chat()`` call in ``received_configs``.
    """

    def __init__(
        self, responses: list[list[LLMChunk]], chat_raises: Exception | None = None
    ) -> None:
        self._responses = list(responses)
        self.chat_raises = chat_raises
        self.received_configs: list[dict] = []
        self.received_tools: list[list] = []

    async def _iter_chunks(self, chunks: list[LLMChunk]) -> AsyncIterator[LLMChunk]:
        for chunk in chunks:
            yield chunk

    def chat(
        self,
        messages: list[dict],
        tools: list,
        model_config: dict,
        *,
        stream: bool,
        runtime_config: dict | None = None,
    ) -> AsyncIterator[LLMChunk]:
        self.received_configs.append(dict(model_config))
        self.received_tools.append(list(tools))

        if self.chat_raises is not None:
            raise self.chat_raises

        response = self._responses.pop(0)
        return self._iter_chunks(response)


class RecordingEmitter(Emitter):
    """Appends ``(method_name, payload)`` tuples to ``events`` for assertion."""

    def __init__(self) -> None:
        self.events: list[tuple[str, object]] = []
        self.warnings: list[str] = []

    async def on_start(self, request) -> None:
        self.events.append(("on_start", request))

    async def on_chunk(self, chunk: LLMChunk) -> None:
        self.events.append(("on_chunk", chunk))

    async def on_tool_call(self, call: object) -> None:
        self.events.append(("on_tool_call", call))

    async def on_tool_result(self, result: ToolResult) -> None:
        self.events.append(("on_tool_result", result))

    async def on_warning(self, message: str) -> None:
        self.warnings.append(message)
        self.events.append(("on_warning", message))

    async def on_final(self, result: LoopResult) -> None:
        self.events.append(("on_final", result))

    async def on_error(self, error: Exception) -> None:
        self.events.append(("on_error", error))


class StubToolRegistry(ToolRegistry):
    """Tool registry backed by sync or async callables for testing.

    Unknown tool names raise ``KeyError`` (matching ``ToolRegistry.execute``
    behaviour) so the loop's error-coalescing path is exercised.
    """

    def __init__(self, tools: dict[str, Callable]) -> None:
        super().__init__()
        for name, fn in tools.items():
            spec = ToolSpec(name=name, description=f"stub {name}")
            self.register(spec, self._make_executor(name, fn))

    @staticmethod
    def _make_executor(name: str, fn: Callable):
        async def executor(args: dict) -> ToolResult:
            if inspect.iscoroutinefunction(fn):
                raw = await fn(args)
            else:
                raw = fn(args)
            return ToolResult(tool_call_id="", content=str(raw), is_error=False)

        return executor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_llm_data(model: str = "fake-model") -> LLMData:
    return LLMData(
        provider="openai",
        config=LLMConfigData(model=model),
    )


def _make_agent_spec(
    max_execution_time: float | None = None,
    max_retry_limit: int | None = None,
    max_rpm: int | None = None,
    max_tool_calls: int | None = None,
    tool_timeout: int | None = None,
    max_consecutive_failures: int | None = None,
) -> AgentSpec:
    return AgentSpec(
        id=1,
        name="test-agent",
        instructions="You are a test assistant.",
        llm=_make_llm_data(),
        max_execution_time=max_execution_time,
        max_retry_limit=max_retry_limit,
        max_rpm=max_rpm,
        max_tool_calls=max_tool_calls,
        tool_timeout=tool_timeout,
        max_consecutive_failures=max_consecutive_failures,
    )


def make_context(
    max_execution_time: float | None = None,
    messages: list[dict] | None = None,
    max_tool_calls: int | None = None,
    tool_timeout: int | None = None,
    max_consecutive_failures: int | None = None,
) -> AgentContext:
    agent = _make_agent_spec(
        max_execution_time=max_execution_time,
        max_tool_calls=max_tool_calls,
        tool_timeout=tool_timeout,
        max_consecutive_failures=max_consecutive_failures,
    )
    return AgentContext(
        agent=agent,
        attachments=[],
        correlation_id="test-corr",
        messages=messages,
    )


def text_chunks(*texts: str) -> list[LLMChunk]:
    return [LLMChunk(delta_text=text) for text in texts]


def tool_chunks(call_id: str, name: str, args: str) -> list[LLMChunk]:
    """Single-chunk tool call (no argument streaming needed for tests)."""
    return [
        LLMChunk(
            tool_call_fragment=ToolCallFragment(
                id=call_id, name=name, arguments_delta=args
            )
        ),
        LLMChunk(finish_reason="tool_calls"),
    ]


# ---------------------------------------------------------------------------
# Tests: model_config derivation
# ---------------------------------------------------------------------------


def test_build_model_config_adds_provider_prefix():
    """Provider prefix is added when model string has no '/'."""
    from app.loop.agent_loop import _build_model_config

    agent = _make_agent_spec()
    context = AgentContext(agent=agent, attachments=[], correlation_id="c")
    config = _build_model_config(context)
    assert config["model"] == "openai/fake-model"


def test_build_model_config_no_double_prefix():
    """Provider prefix is NOT added when model already contains '/'."""
    from app.loop.agent_loop import _build_model_config

    agent = AgentSpec(
        id=1,
        name="a",
        instructions="i",
        llm=LLMData(provider="openai", config=LLMConfigData(model="openai/gpt-4o")),
    )
    context = AgentContext(agent=agent, attachments=[], correlation_id="c")
    config = _build_model_config(context)
    assert config["model"] == "openai/gpt-4o"


# ---------------------------------------------------------------------------
# Tests: loop behaviour
# ---------------------------------------------------------------------------


async def test_single_text_response_no_tools():
    """Plain text response stops with completed, appends one assistant message."""
    emitter = RecordingEmitter()
    context = make_context()
    tools = StubToolRegistry({})
    stop = MaxIterAndNoToolCalls(max_iter=5)

    llm = FakeLLMClient([text_chunks("Hello", " world")])
    loop = DefaultAgentLoop(llm)

    result = await loop.run(context, tools, emitter, stop)

    assert result.stop_reason == "completed"
    assert result.final_text == "Hello world"
    assert result.tool_invocations == 0
    assert result.iterations == 1

    assert len(context.messages) == 1
    assert context.messages[0]["role"] == "assistant"
    assert context.messages[0]["content"] == "Hello world"

    chunk_events = [name for name, _ in emitter.events if name == "on_chunk"]
    assert len(chunk_events) == 2


async def test_tool_call_then_text_response():
    """One tool call followed by a text reply: verify messages, counts, emitter events."""
    emitter = RecordingEmitter()
    context = make_context()
    tools = StubToolRegistry({"get_time": lambda args: "12:00"})
    stop = MaxIterAndNoToolCalls(max_iter=5)

    llm = FakeLLMClient(
        [
            tool_chunks("call_1", "get_time", "{}"),
            text_chunks("The time is 12:00"),
        ]
    )
    loop = DefaultAgentLoop(llm)

    result = await loop.run(context, tools, emitter, stop)

    assert result.stop_reason == "completed"
    assert result.final_text == "The time is 12:00"
    assert result.tool_invocations == 1
    assert result.iterations == 2

    # messages: assistant (tool_calls) → tool → assistant (text)
    assert len(context.messages) == 3
    assert context.messages[0]["role"] == "assistant"
    assert "tool_calls" in context.messages[0]
    assert context.messages[1]["role"] == "tool"
    assert context.messages[1]["tool_call_id"] == "call_1"
    assert context.messages[2]["role"] == "assistant"
    assert context.messages[2]["content"] == "The time is 12:00"

    event_names = [name for name, _ in emitter.events]
    assert "on_tool_call" in event_names
    assert "on_tool_result" in event_names
    tool_call_index = event_names.index("on_tool_call")
    tool_result_index = event_names.index("on_tool_result")
    assert tool_call_index < tool_result_index


async def test_parallel_tool_calls():
    """Two tool calls in one assistant message: both executed, both fed back."""
    emitter = RecordingEmitter()
    context = make_context()
    tools = StubToolRegistry(
        {
            "tool_a": lambda args: "result_a",
            "tool_b": lambda args: "result_b",
        }
    )
    stop = MaxIterAndNoToolCalls(max_iter=5)

    llm = FakeLLMClient(
        [
            [
                LLMChunk(
                    tool_call_fragment=ToolCallFragment(
                        id="c1", name="tool_a", arguments_delta="{}"
                    )
                ),
                LLMChunk(
                    tool_call_fragment=ToolCallFragment(
                        id="c2", name="tool_b", arguments_delta="{}"
                    )
                ),
                LLMChunk(finish_reason="tool_calls"),
            ],
            text_chunks("done"),
        ]
    )
    loop = DefaultAgentLoop(llm)

    result = await loop.run(context, tools, emitter, stop)

    assert result.tool_invocations == 2
    tool_messages = [m for m in context.messages if m["role"] == "tool"]
    assert len(tool_messages) == 2
    tool_ids = {m["tool_call_id"] for m in tool_messages}
    assert tool_ids == {"c1", "c2"}

    tool_result_events: list[ToolResult] = [
        payload
        for name, payload in emitter.events
        if name == "on_tool_result" and isinstance(payload, ToolResult)
    ]
    assert len(tool_result_events) == 2
    for r in tool_result_events:
        assert not r.is_error


async def test_tool_raises_feeds_error_back_and_loop_continues():
    """Tool that raises: error fed back as is_error=True; loop continues to next iteration."""
    emitter = RecordingEmitter()
    context = make_context()

    def bad_tool(args):
        raise RuntimeError("boom")

    tools = StubToolRegistry({"bad": bad_tool})
    stop = MaxIterAndNoToolCalls(max_iter=5)

    llm = FakeLLMClient(
        [
            tool_chunks("c1", "bad", "{}"),
            text_chunks("recovered"),
        ]
    )
    loop = DefaultAgentLoop(llm)

    result = await loop.run(context, tools, emitter, stop)

    assert result.stop_reason == "completed"
    assert result.tool_invocations == 1

    tool_result_events: list[ToolResult] = [
        payload
        for name, payload in emitter.events
        if name == "on_tool_result" and isinstance(payload, ToolResult)
    ]
    assert len(tool_result_events) == 1
    payload = tool_result_events[0]
    assert payload.is_error is True
    assert "boom" in payload.content

    tool_messages = [m for m in context.messages if m["role"] == "tool"]
    assert len(tool_messages) == 1


async def test_tool_json_parse_failure():
    """Malformed JSON args: coalesced into is_error=True ToolResult, loop continues."""
    emitter = RecordingEmitter()
    context = make_context()
    tools = StubToolRegistry({"my_tool": lambda args: "ok"})
    stop = MaxIterAndNoToolCalls(max_iter=5)

    llm = FakeLLMClient(
        [
            [
                LLMChunk(
                    tool_call_fragment=ToolCallFragment(
                        id="c1", name="my_tool", arguments_delta="{bad json"
                    )
                ),
                LLMChunk(finish_reason="tool_calls"),
            ],
            text_chunks("done"),
        ]
    )
    loop = DefaultAgentLoop(llm)

    result = await loop.run(context, tools, emitter, stop)

    assert result.stop_reason == "completed"

    tool_result_events: list[ToolResult] = [
        payload
        for name, payload in emitter.events
        if name == "on_tool_result" and isinstance(payload, ToolResult)
    ]
    assert len(tool_result_events) == 1
    assert tool_result_events[0].is_error is True
    assert "Invalid JSON" in tool_result_events[0].content


async def test_unknown_tool_name():
    """Tool name not in registry: coalesced into is_error=True ToolResult."""
    emitter = RecordingEmitter()
    context = make_context()
    tools = StubToolRegistry({})
    stop = MaxIterAndNoToolCalls(max_iter=5)

    llm = FakeLLMClient(
        [
            tool_chunks("c1", "nonexistent", "{}"),
            text_chunks("done"),
        ]
    )
    loop = DefaultAgentLoop(llm)

    result = await loop.run(context, tools, emitter, stop)

    tool_result_events: list[ToolResult] = [
        payload
        for name, payload in emitter.events
        if name == "on_tool_result" and isinstance(payload, ToolResult)
    ]
    assert len(tool_result_events) == 1
    assert tool_result_events[0].is_error is True
    assert "Unknown tool" in tool_result_events[0].content


async def test_max_iter_reached():
    """Iteration cap hit while still emitting tool calls → max_iter_reached."""
    emitter = RecordingEmitter()
    context = make_context()
    tools = StubToolRegistry({"repeat": lambda args: "x"})
    stop = MaxIterAndNoToolCalls(max_iter=2)

    llm = FakeLLMClient(
        [
            tool_chunks("c1", "repeat", "{}"),
            tool_chunks("c2", "repeat", "{}"),
            text_chunks("never reached"),
        ]
    )
    loop = DefaultAgentLoop(llm)

    result = await loop.run(context, tools, emitter, stop)

    assert result.stop_reason == "max_iter_reached"
    assert result.iterations == 2
    assert result.tool_invocations == 2


async def test_llm_raises_returns_llm_error_no_on_error():
    """LLMClient.chat raises → stop_reason='llm_error', on_error NOT called (loop no longer emits)."""
    emitter = RecordingEmitter()
    context = make_context()
    tools = StubToolRegistry({})
    stop = MaxIterAndNoToolCalls(max_iter=5)

    llm = FakeLLMClient([], chat_raises=RuntimeError("LLM down"))
    loop = DefaultAgentLoop(llm)

    result = await loop.run(context, tools, emitter, stop)

    assert result.stop_reason == "llm_error"
    assert result.iterations == 0
    assert result.tool_invocations == 0
    assert result.error == "LLM down"

    error_events = [payload for name, payload in emitter.events if name == "on_error"]
    assert len(error_events) == 0


async def test_timeout_fires_mid_execution():
    """Wall-clock limit fires during tool execution → stop_reason='timeout', on_error NOT called."""
    emitter = RecordingEmitter()

    async def slow_tool(args):
        await asyncio.sleep(5)
        return "never"

    tools = ToolRegistry()

    async def slow_executor(args: dict) -> ToolResult:
        await slow_tool(args)
        return ToolResult(tool_call_id="", content="never", is_error=False)

    tools.register(ToolSpec(name="slow", description="slow tool"), slow_executor)

    context = make_context(max_execution_time=0.05)
    stop = MaxIterAndNoToolCalls(max_iter=5)

    llm = FakeLLMClient(
        [
            tool_chunks("c1", "slow", "{}"),
        ]
    )
    loop = DefaultAgentLoop(llm)

    result = await loop.run(context, tools, emitter, stop)

    assert result.stop_reason == "timeout"
    assert result.error is not None
    assert "exceeded" in result.error

    error_events = [payload for name, payload in emitter.events if name == "on_error"]
    assert len(error_events) == 0


async def test_streaming_chunk_order_preserved():
    """All chunks observed by on_chunk in exact emission order."""
    emitter = RecordingEmitter()
    context = make_context()
    tools = StubToolRegistry({})
    stop = MaxIterAndNoToolCalls(max_iter=5)

    ordered_chunks = [LLMChunk(delta_text=str(i)) for i in range(5)]
    llm = FakeLLMClient([ordered_chunks])
    loop = DefaultAgentLoop(llm)

    await loop.run(context, tools, emitter, stop)

    observed = [payload for name, payload in emitter.events if name == "on_chunk"]
    assert observed == ordered_chunks


def test_context_starts_with_empty_messages():
    """AgentContext starts with empty messages; prompt is built externally by the runner."""
    agent = AgentSpec(
        id=1,
        name="researcher",
        instructions="You research topics thoroughly.",
        llm=_make_llm_data(),
    )
    context = AgentContext(agent=agent, attachments=[], correlation_id="c")
    assert context.messages == []


async def test_token_usage_aggregated_across_two_iterations():
    """Usage chunks from two iterations are summed: prompt=12, completion=5, total=17,
    cached_prompt_tokens=6, total_cost_usd=0.003."""
    emitter = RecordingEmitter()
    context = make_context()
    tools = StubToolRegistry({"get_time": lambda args: "12:00"})
    stop = MaxIterAndNoToolCalls(max_iter=5)

    iter1_chunks = [
        *tool_chunks("call_1", "get_time", "{}"),
        LLMChunk(
            usage={
                "prompt_tokens": 5,
                "completion_tokens": 3,
                "total_tokens": 8,
                "cached_prompt_tokens": 2,
                "total_cost_usd": 0.001,
            }
        ),
    ]
    iter2_chunks = [
        *text_chunks("The time is 12:00"),
        LLMChunk(
            usage={
                "prompt_tokens": 7,
                "completion_tokens": 2,
                "total_tokens": 9,
                "cached_prompt_tokens": 4,
                "total_cost_usd": 0.002,
            }
        ),
    ]

    llm = FakeLLMClient([iter1_chunks, iter2_chunks])
    loop = DefaultAgentLoop(llm)

    result = await loop.run(context, tools, emitter, stop)

    assert result.stop_reason == "completed"
    assert result.token_usage.prompt_tokens == 12
    assert result.token_usage.completion_tokens == 5
    assert result.token_usage.total_tokens == 17
    assert result.token_usage.cached_prompt_tokens == 6
    assert result.token_usage.total_cost_usd == pytest.approx(0.003)


async def test_token_usage_defaults_to_zero_when_no_usage_chunks():
    """When LLM emits no usage chunks, token_usage fields are all zero."""
    emitter = RecordingEmitter()
    context = make_context()
    tools = StubToolRegistry({})
    stop = MaxIterAndNoToolCalls(max_iter=5)

    llm = FakeLLMClient([text_chunks("hello")])
    loop = DefaultAgentLoop(llm)

    result = await loop.run(context, tools, emitter, stop)

    assert result.token_usage.prompt_tokens == 0
    assert result.token_usage.completion_tokens == 0
    assert result.token_usage.total_tokens == 0
    assert result.token_usage.cached_prompt_tokens == 0
    assert result.token_usage.total_cost_usd == 0.0


# ---------------------------------------------------------------------------
# Tests: tool_choice forwarded through model_config
# ---------------------------------------------------------------------------


async def test_tool_choice_in_context_appears_in_model_config():
    """context.tool_choice set → forwarded to LLM as model_config['tool_choice']."""
    emitter = RecordingEmitter()
    agent = _make_agent_spec()
    choice = {"type": "function", "function": {"name": "submit_final_answer"}}
    context = AgentContext(
        agent=agent,
        attachments=[],
        correlation_id="c",
        tool_choice=choice,
    )
    tools = StubToolRegistry({})
    stop = MaxIterAndNoToolCalls(max_iter=5)

    llm = FakeLLMClient([text_chunks("ok")])
    loop = DefaultAgentLoop(llm)

    await loop.run(context, tools, emitter, stop)

    assert len(llm.received_configs) == 1
    assert llm.received_configs[0]["tool_choice"] == choice


async def test_tool_choice_none_not_present_in_model_config():
    """context.tool_choice=None (default) → 'tool_choice' key absent from model_config."""
    emitter = RecordingEmitter()
    context = make_context()
    tools = StubToolRegistry({})
    stop = MaxIterAndNoToolCalls(max_iter=5)

    llm = FakeLLMClient([text_chunks("ok")])
    loop = DefaultAgentLoop(llm)

    await loop.run(context, tools, emitter, stop)


# ---------------------------------------------------------------------------
# Tests: context window warning
# ---------------------------------------------------------------------------


async def test_context_warning_emitted_once_when_over_ratio(monkeypatch):
    """Tokens >= ratio * context_window → exactly one warning containing the window size."""
    import litellm as _litellm

    from app.loop.agent_loop import DefaultAgentLoop

    monkeypatch.setattr(
        _litellm, "get_model_info", lambda model: {"max_input_tokens": 1000}
    )
    monkeypatch.setattr(_litellm, "token_counter", lambda model, messages: 900)

    emitter = RecordingEmitter()
    context = make_context()
    tools = StubToolRegistry({"ping": lambda args: "pong"})
    stop = MaxIterAndNoToolCalls(max_iter=5)

    # Two iterations: tool call then text reply
    llm = FakeLLMClient(
        [
            tool_chunks("c1", "ping", "{}"),
            text_chunks("done"),
        ]
    )
    loop = DefaultAgentLoop(llm, context_warning_ratio=0.8)

    await loop.run(context, tools, emitter, stop)

    assert len(emitter.warnings) == 1
    assert "1000" in emitter.warnings[0]


async def test_context_warning_not_emitted_when_under_ratio(monkeypatch):
    """Tokens < ratio * context_window → no warning."""
    import litellm as _litellm

    monkeypatch.setattr(
        _litellm, "get_model_info", lambda model: {"max_input_tokens": 1000}
    )
    monkeypatch.setattr(_litellm, "token_counter", lambda model, messages: 100)

    emitter = RecordingEmitter()
    context = make_context()
    tools = StubToolRegistry({})
    stop = MaxIterAndNoToolCalls(max_iter=5)

    llm = FakeLLMClient([text_chunks("ok")])
    loop = DefaultAgentLoop(llm, context_warning_ratio=0.8)

    await loop.run(context, tools, emitter, stop)

    assert emitter.warnings == []


async def test_context_warning_ratio_none_no_warning():
    """context_warning_ratio=None (default) → no warning; get_model_info/token_counter not needed."""
    emitter = RecordingEmitter()
    context = make_context()
    tools = StubToolRegistry({})
    stop = MaxIterAndNoToolCalls(max_iter=5)

    llm = FakeLLMClient([text_chunks("ok")])
    loop = DefaultAgentLoop(llm)  # default ratio=None

    await loop.run(context, tools, emitter, stop)

    assert emitter.warnings == []


async def test_context_warning_get_model_info_raises_no_warning(monkeypatch):
    """get_model_info raising → no warning, run still completes normally."""
    import litellm as _litellm

    def _raise(model):
        raise RuntimeError("model not found")

    monkeypatch.setattr(_litellm, "get_model_info", _raise)

    emitter = RecordingEmitter()
    context = make_context()
    tools = StubToolRegistry({})
    stop = MaxIterAndNoToolCalls(max_iter=5)

    llm = FakeLLMClient([text_chunks("ok")])
    loop = DefaultAgentLoop(llm, context_warning_ratio=0.8)

    result = await loop.run(context, tools, emitter, stop)

    assert result.stop_reason == "completed"
    assert emitter.warnings == []

    assert len(llm.received_configs) == 1
    assert "tool_choice" not in llm.received_configs[0]


# ---------------------------------------------------------------------------
# Tests: max_tool_calls
# ---------------------------------------------------------------------------


def _parallel_tool_call_chunks(*calls: tuple[str, str, str]) -> list[LLMChunk]:
    """Build one assistant response containing several parallel tool calls."""
    chunks = [
        LLMChunk(
            tool_call_fragment=ToolCallFragment(
                id=call_id, name=name, arguments_delta=args
            )
        )
        for call_id, name, args in calls
    ]
    chunks.append(LLMChunk(finish_reason="tool_calls"))
    return chunks


async def test_max_tool_calls_overflow_rejected_with_error_result():
    """3 parallel calls, max_tool_calls=2: only first 2 executed, 3rd rejected."""
    emitter = RecordingEmitter()
    context = make_context(max_tool_calls=2)
    tools = StubToolRegistry(
        {
            "tool_a": lambda args: "a",
            "tool_b": lambda args: "b",
            "tool_c": lambda args: "c",
        }
    )
    stop = MaxIterAndNoToolCalls(max_iter=5)

    llm = FakeLLMClient(
        [
            _parallel_tool_call_chunks(
                ("c1", "tool_a", "{}"), ("c2", "tool_b", "{}"), ("c3", "tool_c", "{}")
            ),
            text_chunks("done"),
        ]
    )
    loop = DefaultAgentLoop(llm)

    result = await loop.run(context, tools, emitter, stop)

    assert result.stop_reason == "completed"
    assert result.tool_invocations == 2

    tool_messages = {
        m["tool_call_id"]: m["content"] for m in context.messages if m["role"] == "tool"
    }
    assert set(tool_messages) == {"c1", "c2", "c3"}
    assert "Tool call limit reached" in tool_messages["c3"]


async def test_max_tool_calls_none_unlimited():
    """3 parallel calls, max_tool_calls=None: all executed."""
    emitter = RecordingEmitter()
    context = make_context(max_tool_calls=None)
    tools = StubToolRegistry(
        {
            "tool_a": lambda args: "a",
            "tool_b": lambda args: "b",
            "tool_c": lambda args: "c",
        }
    )
    stop = MaxIterAndNoToolCalls(max_iter=5)

    llm = FakeLLMClient(
        [
            _parallel_tool_call_chunks(
                ("c1", "tool_a", "{}"), ("c2", "tool_b", "{}"), ("c3", "tool_c", "{}")
            ),
            text_chunks("done"),
        ]
    )
    loop = DefaultAgentLoop(llm)

    result = await loop.run(context, tools, emitter, stop)

    assert result.tool_invocations == 3


async def test_overflow_rejection_does_not_count_toward_consecutive_failures():
    """Rejected overflow calls are not failures and don't trip the failure limit."""
    emitter = RecordingEmitter()
    context = make_context(max_tool_calls=1, max_consecutive_failures=1)
    tools = StubToolRegistry(
        {
            "tool_a": lambda args: "a",
            "tool_b": lambda args: "b",
        }
    )
    stop = MaxIterAndNoToolCalls(max_iter=5)

    llm = FakeLLMClient(
        [
            _parallel_tool_call_chunks(("c1", "tool_a", "{}"), ("c2", "tool_b", "{}")),
            text_chunks("done"),
        ]
    )
    loop = DefaultAgentLoop(llm)

    result = await loop.run(context, tools, emitter, stop)

    assert result.stop_reason == "completed"
    assert result.tool_invocations == 1


# ---------------------------------------------------------------------------
# Tests: tool_timeout
# ---------------------------------------------------------------------------


async def test_tool_timeout_feeds_error_result():
    """Executor slower than timeout: is_error=True, 'timed out after' in content."""
    context = make_context()
    tools = ToolRegistry()

    async def slow_executor(args: dict) -> ToolResult:
        await asyncio.sleep(5)
        return ToolResult(tool_call_id="", content="never", is_error=False)

    tools.register(ToolSpec(name="slow", description="slow tool"), slow_executor)

    llm = FakeLLMClient([])
    loop = DefaultAgentLoop(llm)

    result = await loop._execute_tool(tools, "c1", "slow", "{}", timeout=0.05)

    assert result.is_error is True
    assert "timed out after" in result.content


async def test_tool_timeout_none_no_wrapping():
    """timeout=None: normal tool executes and succeeds without wrapping."""
    context = make_context()
    tools = StubToolRegistry({"ping": lambda args: "pong"})

    llm = FakeLLMClient([])
    loop = DefaultAgentLoop(llm)

    result = await loop._execute_tool(tools, "c1", "ping", "{}", timeout=None)

    assert result.is_error is False
    assert result.content == "pong"


async def test_tool_timeout_counts_as_failure_toward_limit():
    """Tool call exceeding tool_timeout counts as a failure toward max_consecutive_failures."""
    emitter = RecordingEmitter()
    context = make_context(tool_timeout=1, max_consecutive_failures=1)
    tools = ToolRegistry()

    async def slow_executor(args: dict) -> ToolResult:
        await asyncio.sleep(2)
        return ToolResult(tool_call_id="", content="never", is_error=False)

    tools.register(ToolSpec(name="slow", description="slow tool"), slow_executor)
    stop = MaxIterAndNoToolCalls(max_iter=5)

    llm = FakeLLMClient(
        [
            tool_chunks("c1", "slow", "{}"),
            text_chunks("summary after timeout"),
        ]
    )
    loop = DefaultAgentLoop(llm)

    result = await loop.run(context, tools, emitter, stop)

    assert result.stop_reason == "max_consecutive_failures"


# ---------------------------------------------------------------------------
# Tests: max_consecutive_failures
# ---------------------------------------------------------------------------


async def test_consecutive_failures_stops_gracefully_with_summary():
    """N consecutive failures trigger a no-tools finalization LLM call."""
    emitter = RecordingEmitter()
    context = make_context(max_consecutive_failures=2)

    def bad_tool(args):
        raise RuntimeError("boom")

    tools = StubToolRegistry({"bad": bad_tool})
    stop = MaxIterAndNoToolCalls(max_iter=10)

    llm = FakeLLMClient(
        [
            tool_chunks("c1", "bad", "{}"),
            tool_chunks("c2", "bad", "{}"),
            text_chunks("I tried X; it failed because Y"),
        ]
    )
    loop = DefaultAgentLoop(llm)

    result = await loop.run(context, tools, emitter, stop)

    assert result.stop_reason == "max_consecutive_failures"
    assert result.final_text == "I tried X; it failed because Y"
    assert result.error is None

    user_messages = [m for m in context.messages if m["role"] == "user"]
    assert any("consecutive" in m["content"] for m in user_messages)

    assert llm.received_tools[-1] == []
    assert "tool_choice" not in llm.received_configs[-1]

    assistant_messages = [m for m in context.messages if m["role"] == "assistant"]
    assert assistant_messages[-1]["content"] == "I tried X; it failed because Y"


async def test_consecutive_failures_reset_on_success():
    """A successful call resets the consecutive-failure counter."""
    emitter = RecordingEmitter()
    context = make_context(max_consecutive_failures=2)

    calls = {"count": 0}

    def flaky_tool(args):
        calls["count"] += 1
        if calls["count"] in (1, 3):
            raise RuntimeError("boom")
        return "ok"

    tools = StubToolRegistry({"flaky": flaky_tool})
    stop = MaxIterAndNoToolCalls(max_iter=10)

    llm = FakeLLMClient(
        [
            tool_chunks("c1", "flaky", "{}"),
            tool_chunks("c2", "flaky", "{}"),
            tool_chunks("c3", "flaky", "{}"),
            text_chunks("done"),
        ]
    )
    loop = DefaultAgentLoop(llm)

    result = await loop.run(context, tools, emitter, stop)

    assert result.stop_reason == "completed"


async def test_failure_limit_mid_batch_rejects_remaining_calls():
    """Failure limit hit mid-batch: remaining calls in the same batch are skipped."""
    emitter = RecordingEmitter()
    context = make_context(max_consecutive_failures=1)

    def bad_tool(args):
        raise RuntimeError("boom")

    second_call_spy = {"invoked": False}

    def spy_tool(args):
        second_call_spy["invoked"] = True
        return "should not run"

    tools = StubToolRegistry({"bad": bad_tool, "spy": spy_tool})
    stop = MaxIterAndNoToolCalls(max_iter=10)

    llm = FakeLLMClient(
        [
            _parallel_tool_call_chunks(("c1", "bad", "{}"), ("c2", "spy", "{}")),
            text_chunks("summary"),
        ]
    )
    loop = DefaultAgentLoop(llm)

    result = await loop.run(context, tools, emitter, stop)

    assert second_call_spy["invoked"] is False
    tool_messages = {
        m["tool_call_id"]: m["content"] for m in context.messages if m["role"] == "tool"
    }
    assert "not executed" in tool_messages["c2"]
    assert result.stop_reason == "max_consecutive_failures"


async def test_consecutive_failures_none_disabled():
    """max_consecutive_failures=None: failure limit never trips, max_iter governs instead."""
    emitter = RecordingEmitter()
    context = make_context(max_consecutive_failures=None)

    def bad_tool(args):
        raise RuntimeError("boom")

    tools = StubToolRegistry({"bad": bad_tool})
    stop = MaxIterAndNoToolCalls(max_iter=2)

    llm = FakeLLMClient(
        [
            tool_chunks("c1", "bad", "{}"),
            tool_chunks("c2", "bad", "{}"),
            text_chunks("never reached"),
        ]
    )
    loop = DefaultAgentLoop(llm)

    result = await loop.run(context, tools, emitter, stop)

    assert result.stop_reason == "max_iter_reached"


async def test_finalization_token_usage_accumulated():
    """Usage chunks from the finalization LLM call are summed into the result."""
    emitter = RecordingEmitter()
    context = make_context(max_consecutive_failures=1)

    def bad_tool(args):
        raise RuntimeError("boom")

    tools = StubToolRegistry({"bad": bad_tool})
    stop = MaxIterAndNoToolCalls(max_iter=10)

    finalize_chunks = [
        *text_chunks("summary text"),
        LLMChunk(
            usage={
                "prompt_tokens": 10,
                "completion_tokens": 4,
                "total_tokens": 14,
                "total_cost_usd": 0.0025,
            }
        ),
    ]

    llm = FakeLLMClient(
        [
            tool_chunks("c1", "bad", "{}"),
            finalize_chunks,
        ]
    )
    loop = DefaultAgentLoop(llm)

    result = await loop.run(context, tools, emitter, stop)

    assert result.stop_reason == "max_consecutive_failures"
    assert result.token_usage.prompt_tokens == 10
    assert result.token_usage.completion_tokens == 4
    assert result.token_usage.total_tokens == 14
    assert result.token_usage.total_cost_usd == pytest.approx(0.0025)
