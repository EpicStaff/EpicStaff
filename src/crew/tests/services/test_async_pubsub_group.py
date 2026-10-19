import asyncio

import fakeredis
import pytest

from services.redis_service import AsyncPubSubGroup, AsyncPubsubSubscriber


@pytest.mark.asyncio
async def test_failing_callback_does_not_drop_the_next_message():
    group = AsyncPubSubGroup("channel", fakeredis.FakeAsyncRedis(decode_responses=True))
    received: list[str] = []

    async def failing_callback(message):
        raise ValueError("malformed message")

    async def recording_callback(message):
        received.append(message["data"])

    group.subscribe(AsyncPubsubSubscriber(failing_callback))
    group.subscribe(AsyncPubsubSubscriber(recording_callback))
    await group.start()
    try:
        await group.publish("first")
        await group.publish("second")
        # The old reader reconnected for 1 s after a failing callback, so a 0.5 s
        # wait fails on it while staying generous for a slow CI runner.
        async with asyncio.timeout(0.5):
            while len(received) < 2:
                await asyncio.sleep(0.01)
    finally:
        await group.stop()

    assert received == ["first", "second"]
