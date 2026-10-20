import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import anyio
from application.ports import AbstractFanout
from redis.asyncio import Redis


class RedisFanout(AbstractFanout):
    def __init__(self, redis: Redis):
        self._redis = redis

    async def publish(self, channel: str, event: dict) -> None:
        await self._redis.publish(channel, json.dumps(event))

    @asynccontextmanager
    async def listen(self, channel: str, idle_seconds: float):
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(channel)
        try:
            yield self._messages(pubsub, idle_seconds)
        finally:
            # A dropped client cancels the response task; unshielded, the cleanup is cancelled too and leaks the connection.
            with anyio.CancelScope(shield=True):
                try:
                    await pubsub.unsubscribe(channel)
                finally:
                    await pubsub.aclose()

    @staticmethod
    async def _messages(pubsub, idle_seconds: float) -> AsyncIterator[dict | None]:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + idle_seconds
        while True:
            message = await pubsub.get_message(
                ignore_subscribe_messages=True, timeout=max(0.01, deadline - loop.time())
            )
            if message is None:
                # fakeredis returns at once instead of waiting out the timeout; only report idle once it truly elapsed
                if loop.time() < deadline:
                    await asyncio.sleep(0.01)
                    continue
                yield None
                deadline = loop.time() + idle_seconds
                continue
            if message.get("type") != "message":
                continue
            data = message["data"]
            yield json.loads(data.decode("utf-8") if isinstance(data, bytes) else data)
            deadline = loop.time() + idle_seconds
