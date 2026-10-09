import time

import pytest

from tables.services.redis_service import RedisService


class _FinitePubSub:
    """Delivers a fixed list of messages, then ends like a closed subscription."""

    def __init__(self, messages):
        self._messages = messages

    async def listen(self):
        for message in self._messages:
            yield message

    async def unsubscribe(self, *channels):
        pass

    async def close(self):
        pass


@pytest.mark.asyncio
async def test_a_burst_of_messages_is_read_without_waiting_between_them():
    burst = [
        {"type": "message", "channel": "session:update:1:messages", "data": str(index)}
        for index in range(300)
    ]
    started_at = time.monotonic()

    received = [
        message
        async for message in RedisService().redis_get_message(
            channels=["session:update:1:messages"], pubsub=_FinitePubSub(burst)
        )
    ]

    assert [message["data"] for message in received] == [str(index) for index in range(300)]
    # Any fixed pause per message would take seconds here: 10 ms each is 3 s.
    assert time.monotonic() - started_at < 1
