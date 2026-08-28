import os
import json
import redis.asyncio as aioredis
from redis.client import PubSub
from redis.retry import Retry
from redis.backoff import ExponentialBackoff

from helpers.logger import logger


class RedisService:
    def __init__(self):
        self.aioredis_client = None
        self._retry = Retry(backoff=ExponentialBackoff(cap=3), retries=10)

    async def init_redis(self):
        host = os.environ.get("REDIS_HOST", "localhost")
        port = os.environ.get("REDIS_PORT", 6379)
        password = os.environ.get("REDIS_PASSWORD")
        self.aioredis_client = await aioredis.from_url(
            f"redis://{host}:{port}",
            retry=self._retry,
            password=password,
        )

    async def async_subscribe(self, channel: str) -> PubSub:
        pubsub = self.aioredis_client.pubsub()
        await pubsub.subscribe(channel)
        return pubsub

    async def async_publish(self, channel: str, message: object):
        await self.aioredis_client.publish(channel, json.dumps(message))
        logger.info(f"Message published to channel '{channel}'.")
