import json
import redis.asyncio as aioredis
from loguru import logger
from redis.client import PubSub
from utils.singleton_meta import SingletonMeta

from domain.ports.i_redis_messaging_service import IRedisMessagingService


class RedisService(IRedisMessagingService, metaclass=SingletonMeta):
    def __init__(self, host: str, port: int, password: str):
        self.host = host
        self.port = port
        self.password = password
        self.aioredis_client: aioredis.Redis | None = None

    async def connect(self):
        """Establish connection with Redis (idempotent)."""
        if self.aioredis_client is not None:
            return
        self.aioredis_client = await aioredis.from_url(
            f"redis://{self.host}:{self.port}",
            password=self.password,
            decode_responses=True,
        )
        logger.info("Connected to Redis.")

    async def async_subscribe(self, channel: str) -> PubSub:
        """Subscribe to a Redis channel."""
        pubsub = self.aioredis_client.pubsub()
        await pubsub.subscribe(channel)
        return pubsub

    async def async_publish(self, channel: str, message: object):
        """Publish a message to a Redis channel."""
        await self.aioredis_client.publish(channel, json.dumps(message))

        logger.debug("Message published to channel '%s'", channel)

    async def listen_to_channel(self, channel: str, callback):
        """Listen for messages on a Redis channel."""
        pubsub = await self.async_subscribe(channel)
        logger.info("Subscribed to Redis channel: '%s'", channel)

        async for message in pubsub.listen():
            if message["type"] == "message":
                data = message["data"]
                logger.info("Received message from channel '%s'.", channel)
                await callback(data)
