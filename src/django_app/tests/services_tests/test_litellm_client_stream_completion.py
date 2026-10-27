"""Stream tests for LiteLLMClient.stream_completion.

`litellm.acompletion` is the LLM provider boundary and is replaced by a stub that
returns SimpleNamespace chunks; the client's own chunk handling runs for real.
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from litellm.litellm_core_utils.streaming_handler import CustomStreamWrapper
from litellm.llms.groq.chat.transformation import GroqChatCompletionStreamingHandler

from src.shared.models import LLMConfigData
from tables.services.llm_clients.base import DoneEvent, LLMProviderError, TokenEvent
from tables.services.llm_clients.litellm_client import LiteLLMClient


def make_client(**config_fields) -> LiteLLMClient:
    return LiteLLMClient(
        LLMConfigData(model="gpt-4o", **config_fields), provider_name="openai", api_key=None
    )


def make_chunk(content: str | None = None, finish_reason: str | None = None):
    delta = SimpleNamespace(content=content, tool_calls=None)
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta, finish_reason=finish_reason)])


def make_acompletion_stub(chunks: list, received_kwargs: dict | None = None):
    async def chunk_stream():
        for chunk in chunks:
            yield chunk

    async def acompletion_stub(**kwargs):
        if received_kwargs is not None:
            received_kwargs.update(kwargs)
        return chunk_stream()

    return acompletion_stub


async def collect_events(
    chunks: list, client: LiteLLMClient | None = None, received_kwargs: dict | None = None
) -> list:
    client = client or make_client()
    with patch(
        "tables.services.llm_clients.litellm_client.litellm.acompletion",
        new=make_acompletion_stub(chunks, received_kwargs),
    ):
        return [event async for event in client.stream_completion([], [])]


@pytest.mark.asyncio
@pytest.mark.parametrize("finish_reason", ["length", "stop"])
async def test_finish_reason_is_propagated_into_done_event(finish_reason):
    events = await collect_events(
        [
            make_chunk(content="Hel"),
            make_chunk(content="lo"),
            make_chunk(finish_reason=finish_reason),
        ]
    )

    assert [event.content for event in events if isinstance(event, TokenEvent)] == ["Hel", "lo"]
    assert events[-1] == DoneEvent(finish_reason=finish_reason)


@pytest.mark.asyncio
async def test_finish_reason_keeps_last_non_empty_value():
    events = await collect_events(
        [
            make_chunk(content="Hello", finish_reason="length"),
            make_chunk(content=None, finish_reason=None),
        ]
    )

    assert events[-1].finish_reason == "length"


@pytest.mark.asyncio
async def test_finish_reason_is_none_when_provider_reports_none():
    events = await collect_events([make_chunk(content="Hello")])

    assert events[-1] == DoneEvent(finish_reason=None)


@pytest.mark.asyncio
async def test_generation_params_except_stop_reach_litellm_acompletion():
    received_kwargs: dict = {}
    client = make_client(reasoning_effort="low", stop=["END"], logit_bias={50256: -100.0})

    await collect_events([make_chunk(content="ok", finish_reason="stop")], client, received_kwargs)

    assert received_kwargs["reasoning_effort"] == "low"
    assert "stop" not in received_kwargs
    assert received_kwargs["logit_bias"] == {50256: -100.0}


@pytest.mark.asyncio
async def test_unset_reasoning_effort_is_not_sent_to_litellm_acompletion():
    received_kwargs: dict = {}

    await collect_events([make_chunk(content="ok", finish_reason="stop")], None, received_kwargs)

    assert "reasoning_effort" not in received_kwargs


GROQ_MESSAGE = (
    "Tool call validation failed: attempted to call tool 'json' which was not in request.tools"
)

GROQ_TOOL_USE_FAILED_CHUNK = {
    "error": {
        "message": GROQ_MESSAGE,
        "type": "invalid_request_error",
        "code": "tool_use_failed",
        "failed_generation": "{}",
    }
}

GROQ_CONTENT_CHUNK = {
    "id": "chatcmpl-1",
    "object": "chat.completion.chunk",
    "created": 1,
    "model": "openai/gpt-oss-120b",
    "choices": [{"index": 0, "delta": {"content": "Hel"}, "finish_reason": None}],
}


def litellm_stream_over(raw_groq_chunks: list[dict]) -> CustomStreamWrapper:
    """Build the stream litellm itself hands out for a Groq response.

    litellm's own Groq handler and CustomStreamWrapper run for real, so the exception that
    comes out of iterating is the one litellm produces. Only the raw HTTP body (the fake
    chunks) and the logging object, which litellm needs only for its callbacks, are
    stand-ins.
    """

    async def raw_http_stream():
        for chunk in raw_groq_chunks:
            yield "data: " + json.dumps(chunk)

    logging_obj = MagicMock(model_call_details={})
    logging_obj.dispatch_failure_handlers = AsyncMock()
    logging_obj.async_failure_handler = AsyncMock()
    return CustomStreamWrapper(
        completion_stream=GroqChatCompletionStreamingHandler(
            streaming_response=raw_http_stream(), sync_stream=False
        ),
        model="openai/gpt-oss-120b",
        custom_llm_provider="groq",
        logging_obj=logging_obj,
    )


def make_groq_client() -> LiteLLMClient:
    return LiteLLMClient(
        LLMConfigData(model="openai/gpt-oss-120b"), provider_name="groq", api_key=None
    )


async def stream_events_from(response) -> list:
    async def acompletion_stub(**kwargs):
        return response

    with patch(
        "tables.services.llm_clients.litellm_client.litellm.acompletion", new=acompletion_stub
    ):
        return [event async for event in make_groq_client().stream_completion([], [])]


LITELLM_FIXED_MESSAGE = (
    "litellm no longer turns a Groq error chunk into a ValueError. The bug this client "
    "works around is fixed upstream: re-check whether _provider_error_from still needs to "
    "walk the exception chain (the provider body may now be on the raised error itself) "
    "and simplify it and these tests accordingly."
)


@pytest.mark.asyncio
async def test_litellm_still_crashes_with_a_value_error_on_a_groq_error_chunk():
    try:
        async for _chunk in litellm_stream_over([GROQ_TOOL_USE_FAILED_CHUNK]):
            pass  # pragma: no cover
    except Exception as exc:
        assert isinstance(exc, ValueError), LITELLM_FIXED_MESSAGE
    else:
        pytest.fail(LITELLM_FIXED_MESSAGE)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw_groq_chunks",
    [
        [GROQ_TOOL_USE_FAILED_CHUNK],
        [GROQ_CONTENT_CHUNK, GROQ_TOOL_USE_FAILED_CHUNK],
    ],
    ids=["before_first_chunk", "after_first_chunk"],
)
async def test_groq_error_chunk_surfaces_as_provider_error(raw_groq_chunks):
    with pytest.raises(LLMProviderError) as excinfo:
        await stream_events_from(litellm_stream_over(raw_groq_chunks))

    assert excinfo.value.code == "tool_use_failed"
    assert excinfo.value.provider == "groq"
    assert excinfo.value.message == GROQ_MESSAGE


@pytest.mark.asyncio
async def test_error_without_provider_body_is_reraised_unchanged():
    async def failing_stream():
        raise RuntimeError("connection reset")
        yield  # pragma: no cover

    with pytest.raises(RuntimeError, match="connection reset"):
        await stream_events_from(failing_stream())


@pytest.mark.asyncio
async def test_cyclic_exception_chain_without_provider_body_is_reraised():
    async def failing_stream():
        first = RuntimeError("first")
        second = RuntimeError("second")
        first.__context__ = second
        second.__context__ = first
        raise first
        yield  # pragma: no cover

    with pytest.raises(RuntimeError, match="first"):
        await stream_events_from(failing_stream())


@pytest.mark.asyncio
async def test_error_wrapped_in_an_error_envelope_body_is_found():
    class ProviderRejected(Exception):
        body = {"error": {"message": "rate limited", "code": "rate_limit_exceeded"}}

    async def failing_stream():
        raise ProviderRejected()
        yield  # pragma: no cover

    with pytest.raises(LLMProviderError) as excinfo:
        await stream_events_from(failing_stream())

    assert (excinfo.value.code, excinfo.value.message) == ("rate_limit_exceeded", "rate limited")


@pytest.mark.asyncio
async def test_provider_message_is_flattened_to_one_line():
    class ProviderRejected(Exception):
        body = {"message": "rate limited\nFAKE LOG LINE", "code": "rate_limit_exceeded"}

    async def failing_stream():
        raise ProviderRejected()
        yield  # pragma: no cover

    with pytest.raises(LLMProviderError) as excinfo:
        await stream_events_from(failing_stream())

    assert excinfo.value.message == "rate limited FAKE LOG LINE"


@pytest.mark.asyncio
async def test_original_exception_wins_over_context():
    class ProviderRejected(Exception):
        def __init__(self, message):
            super().__init__(message)
            self.body = {"message": message, "code": "a"}

    async def failing_stream():
        try:
            raise ProviderRejected("from context")
        except ProviderRejected:
            error = ValueError("wrapper")
            error.original_exception = ProviderRejected("from original")
            raise error
        yield  # pragma: no cover

    with pytest.raises(LLMProviderError) as excinfo:
        await stream_events_from(failing_stream())

    assert excinfo.value.message == "from original"
