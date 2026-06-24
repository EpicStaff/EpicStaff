import json
from typing import AsyncIterable, Any, Iterable

from redis import Redis as SyncRedis, RedisError
from redis.asyncio import Redis as AsyncRedis

from communication.errors import BrokerOperationError
from communication.error_handler import handle_error
from communication.brokers.abstract import AbstractBroker


class RedisPubSubBroker(AbstractBroker):
    """Redis Pub/Sub implementation of Broker.

    Args:
        url: Redis connection URL (e.g. redis://host:6379/0).
    """

    def __init__(self, url: str):
        self._sync_client = SyncRedis.from_url(url)
        self._async_client = AsyncRedis.from_url(url)

    def send(self, channel: str, data: dict[str, Any]):
        with handle_error(RedisError, BrokerOperationError, "send", channel):
            raw_data = json.dumps(data)
            self._sync_client.publish(channel, raw_data)

    async def asend(self, channel: str, data: dict[str, Any]):
        with handle_error(RedisError, BrokerOperationError, "asend", channel):
            raw_data = json.dumps(data)
            await self._async_client.publish(channel, raw_data)

    def receive(self, channel: str) -> Iterable[dict[str, Any]]:
        with handle_error(RedisError, BrokerOperationError, "receive", channel):
            pubsub = self._sync_client.pubsub()
            pubsub.subscribe(channel)

        for msg in pubsub.listen():
            if msg["type"] != "message":
                continue
            data = json.loads(msg["data"])
            yield data

    async def areceive(self, channel: str) -> AsyncIterable[dict[str, Any]]:
        with handle_error(RedisError, BrokerOperationError, "areceive", channel):
            pubsub = self._async_client.pubsub()
            await pubsub.subscribe(channel)

        async for msg in pubsub.listen():
            if msg["type"] != "message":
                continue
            data = json.loads(msg["data"])
            yield data
