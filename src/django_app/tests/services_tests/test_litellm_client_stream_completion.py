"""Stream tests for LiteLLMClient.stream_completion.

`litellm.acompletion` is the LLM provider boundary and is replaced by a stub that
returns SimpleNamespace chunks; the client's own chunk handling runs for real.
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.shared.models import LLMConfigData
from tables.services.llm_clients.base import DoneEvent, TokenEvent
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
