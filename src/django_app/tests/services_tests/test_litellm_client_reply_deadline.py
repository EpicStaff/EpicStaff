"""One wall-clock deadline for a whole LiteLLMClient reply.

Invariant: the model's reply must arrive in full within the config's timeout, capped at the
deployment maximum (DJANGO_LLM_CONFIG_MAX_TIMEOUT); a config without a timeout gets the
maximum. litellm's own timeout bounds each read only, so a provider that keeps trickling
chunks, or never answers the call, is cut off at the deadline and reported as an
LLMProviderError with code "timeout"; the provider stream it cut off is closed.

Only the deadline is reported that way: a transport's own TimeoutError raised before the
deadline stays what it is. The deadline bounds waiting for the provider, never the
caller's own work between two chunks.

`litellm.acompletion` is the provider boundary and is replaced by a stub; the client's
stream handling runs for real.
"""

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.shared.models import LLMConfigData
from tables.services.llm_clients import litellm_client
from tables.services.llm_clients.base import LLMProviderError, TokenEvent
from tables.services.llm_clients.litellm_client import LiteLLMClient

SHORT_TIMEOUT_SECONDS = 0.3
# Far beyond SHORT_TIMEOUT_SECONDS, and finite, so code without a deadline finishes
# (and fails the assertions) instead of hanging the suite.
STALL_SECONDS = 3.0
# Generous for a 0.3s deadline on a loaded CI runner, far below STALL_SECONDS.
CUT_OFF_WITHIN_SECONDS = 2.0


def make_client(timeout) -> LiteLLMClient:
    return LiteLLMClient(
        LLMConfigData(model="gpt-4o", timeout=timeout), provider_name="openai", api_key=None
    )


def make_chunk(content: str | None = None, finish_reason: str | None = None):
    delta = SimpleNamespace(content=content, tool_calls=None)
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta, finish_reason=finish_reason)])


class FakeProviderStream:
    """A provider stream sending `chunks`, waiting `interval` seconds before each one."""

    def __init__(self, chunks: list, interval: float = 0.0):
        self._chunks = iter(chunks)
        self._interval = interval
        self.closed = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._interval:
            await asyncio.sleep(self._interval)
        try:
            return next(self._chunks)
        except StopIteration:
            raise StopAsyncIteration from None

    async def aclose(self):
        self.closed = True


def trickling_stream() -> FakeProviderStream:
    # Each chunk arrives well within any per-read timeout; all of them take STALL_SECONDS.
    return FakeProviderStream([make_chunk(content="x")] * 60, interval=STALL_SECONDS / 60)


def answering_with(stream):
    async def acompletion_stub(**kwargs):
        return stream

    return acompletion_stub


async def consume(client: LiteLLMClient, acompletion_stub) -> list:
    with patch(
        "tables.services.llm_clients.litellm_client.litellm.acompletion", new=acompletion_stub
    ):
        return [event async for event in client.stream_completion([], [])]


async def assert_cut_off_at_the_deadline(client: LiteLLMClient, acompletion_stub) -> None:
    started = time.monotonic()

    with pytest.raises(LLMProviderError) as excinfo:
        await consume(client, acompletion_stub)

    assert time.monotonic() - started < CUT_OFF_WITHIN_SECONDS
    assert (excinfo.value.code, excinfo.value.provider) == ("timeout", "openai")


@pytest.mark.asyncio
async def test_a_reply_trickling_past_the_timeout_is_cut_off():
    await assert_cut_off_at_the_deadline(
        make_client(SHORT_TIMEOUT_SECONDS), answering_with(trickling_stream())
    )


@pytest.mark.asyncio
async def test_a_call_that_never_answers_is_cut_off():
    async def hanging_acompletion(**kwargs):
        await asyncio.sleep(STALL_SECONDS)
        return FakeProviderStream([])

    await assert_cut_off_at_the_deadline(make_client(SHORT_TIMEOUT_SECONDS), hanging_acompletion)


@pytest.mark.asyncio
@pytest.mark.parametrize("config_timeout", [None, 100], ids=["unset", "above-maximum"])
async def test_the_deadline_is_capped_at_the_deployment_maximum(monkeypatch, config_timeout):
    monkeypatch.setattr(litellm_client, "LLM_CONFIG_TIMEOUT_MAX_SECONDS", SHORT_TIMEOUT_SECONDS)

    await assert_cut_off_at_the_deadline(
        make_client(config_timeout), answering_with(trickling_stream())
    )


@pytest.mark.asyncio
async def test_the_provider_stream_is_closed_when_the_deadline_cuts_it_off():
    stream = trickling_stream()

    with pytest.raises(LLMProviderError):
        await consume(make_client(SHORT_TIMEOUT_SECONDS), answering_with(stream))

    assert stream.closed


@pytest.mark.asyncio
async def test_a_reply_within_the_timeout_is_delivered():
    stream = FakeProviderStream(
        [make_chunk(content="Hel"), make_chunk(content="lo"), make_chunk(finish_reason="stop")]
    )

    events = await consume(make_client(SHORT_TIMEOUT_SECONDS), answering_with(stream))

    assert [event.content for event in events if isinstance(event, TokenEvent)] == ["Hel", "lo"]


@pytest.mark.asyncio
async def test_a_transport_timeout_before_the_deadline_is_not_reported_as_the_deadline():
    class TimingOutStream(FakeProviderStream):
        async def __anext__(self):
            raise TimeoutError("read timed out")

    with pytest.raises(TimeoutError, match="read timed out"):
        await consume(make_client(30), answering_with(TimingOutStream([])))


@pytest.mark.asyncio
async def test_the_callers_work_between_chunks_is_not_cut_off_by_the_deadline():
    stream = FakeProviderStream([make_chunk(content="first"), make_chunk(content="second")])
    resumed_after_slow_work = False

    with patch(
        "tables.services.llm_clients.litellm_client.litellm.acompletion",
        new=answering_with(stream),
    ):
        try:
            async for event in make_client(SHORT_TIMEOUT_SECONDS).stream_completion([], []):
                if isinstance(event, TokenEvent) and event.content == "first":
                    # The caller's own work outlasts the deadline.
                    await asyncio.sleep(SHORT_TIMEOUT_SECONDS * 2)
                    resumed_after_slow_work = True
        except LLMProviderError:
            # Fetching the next chunk after the deadline may fail; the caller's work did not.
            pass

    assert resumed_after_slow_work
