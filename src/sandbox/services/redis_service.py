import json
import redis.asyncio as aioredis
from redis.client import PubSub
from redis.retry import Retry
from redis.backoff import ExponentialBackoff
from loguru import logger


class RedisService:
    def __init__(self, host: str, port: int, user: str, password: str):
        self.host = host
        self.port = port
        self.user = user
        self.password = password

        self.aioredis_client: aioredis.Redis | None = None
        self._retry = Retry(backoff=ExponentialBackoff(cap=3), retries=10)

    async def connect(self):
        self.aioredis_client = await aioredis.from_url(
            f"redis://{self.host}:{self.port}",
            username=self.user,
            password=self.password,
            decode_responses=True,
            retry=self._retry,
        )

    async def async_subscribe(self, channel: str) -> PubSub:
        pubsub = self.aioredis_client.pubsub()
        await pubsub.subscribe(channel)
        return pubsub

    async def async_publish(self, channel: str, message: object):
        await self.aioredis_client.publish(channel, json.dumps(message))
        logger.info(f"Message published to channel '{channel}'.")
