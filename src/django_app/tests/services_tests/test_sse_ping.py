import asyncio

import fakeredis
import pytest

from tables.utils import mixins
from tables.utils.mixins import SSEMixin

LIVE_CHANNEL = "session:update:1:status"


class _StubStream(SSEMixin):
    ping_interval = 0.05

    async def get_initial_data(self):
        return
        yield

    async def get_live_updates(self, pubsub):
        return
        yield


async def _quiet_then_message(release: asyncio.Event, cleaned_up: asyncio.Event):
    """A live-update generator that, like pubsub.listen(), blocks until it is released."""
    try:
        await release.wait()
        yield {"event": "status", "data": {"status": "end"}}
    finally:
        cleaned_up.set()


@pytest.mark.asyncio
async def test_idle_stream_sends_pings_and_still_delivers_data_afterwards():
    release = asyncio.Event()
    cleaned_up = asyncio.Event()
    stream = _StubStream()
    frames = stream._data_generator(lambda: _quiet_then_message(release, cleaned_up))

    first = await asyncio.wait_for(anext(frames), timeout=2)
    second = await asyncio.wait_for(anext(frames), timeout=2)
    release.set()
    event_line = await asyncio.wait_for(anext(frames), timeout=2)
    data_line = await asyncio.wait_for(anext(frames), timeout=2)
    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(anext(frames), timeout=2)

    assert [first, second] == [": ping\n\n", ": ping\n\n"]
    assert event_line == "event: status\n"
    assert data_line == 'data: {"status": "end"}\n\n'
    assert cleaned_up.is_set()


@pytest.mark.asyncio
async def test_busy_stream_sends_no_ping():
    async def burst():
        for index in range(3):
            yield {"data": index}

    stream = _StubStream()
    stream.ping_interval = 60

    frames = [frame async for frame in stream._data_generator(burst)]

    assert frames == ["data: 0\n\n", "data: 1\n\n", "data: 2\n\n"]


@pytest.mark.asyncio
async def test_closing_an_idle_stream_cancels_the_pending_read():
    release = asyncio.Event()
    cleaned_up = asyncio.Event()
    frames = _StubStream()._data_generator(lambda: _quiet_then_message(release, cleaned_up))

    assert await asyncio.wait_for(anext(frames), timeout=2) == ": ping\n\n"
    await frames.aclose()

    assert cleaned_up.is_set()


class _IdleLiveStream(SSEMixin):
    """A stream subscribed to one channel that nothing is ever published on."""

    ping_interval = 0.05

    def __init__(self, cleaned_up: asyncio.Event):
        super().__init__()
        self.cleaned_up = cleaned_up

    def get_channels(self):
        return [LIVE_CHANNEL]

    async def get_initial_data(self):
        return
        yield

    async def get_live_updates(self, pubsub):
        try:
            async for message in mixins.redis_service.redis_get_message(
                channels=[LIVE_CHANNEL], pubsub=pubsub
            ):
                yield message
        finally:
            self.cleaned_up.set()


@pytest.fixture
def fake_async_redis(monkeypatch):
    redis_client = fakeredis.FakeAsyncRedis(decode_responses=True)
    monkeypatch.setattr(mixins.redis_service, "_async_redis_client", redis_client)
    monkeypatch.setattr(mixins, "start_periodic_malloc_trim", lambda: None)
    yield redis_client


@pytest.mark.asyncio
async def test_closing_an_idle_event_stream_after_a_ping_runs_its_cleanup(
    fake_async_redis,
):
    cleaned_up = asyncio.Event()
    active_streams_before = mixins._active_sse_count
    frames = _IdleLiveStream(cleaned_up).event_stream()

    first_frame = await asyncio.wait_for(anext(frames), timeout=2)
    await frames.aclose()

    other_tasks = [task for task in asyncio.all_tasks() if task is not asyncio.current_task()]
    assert first_frame == ": ping\n\n"
    assert cleaned_up.is_set()
    assert other_tasks == []
    assert mixins._active_sse_count == active_streams_before
    assert await fake_async_redis.pubsub_numsub(LIVE_CHANNEL) == [(LIVE_CHANNEL, 0)]
