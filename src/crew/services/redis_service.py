import json
import os
import redis.asyncio as aioredis
from redis import Redis
from loguru import logger
from typing import List, Union
from redis.client import PubSub

from utils.singleton_meta import SingletonMeta

SESSION_STATUS_CHANNEL = os.environ.get(
    "SESSION_STATUS_CHANNEL", "sessions:session_status"
)


class RedisService(metaclass=SingletonMeta):
    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port

        self.aioredis_client: aioredis.Redis | None = None
        self.sync_redis_client: Redis | None = None

    async def connect(self):
        try:
            self.aioredis_client = await aioredis.from_url(
                f"redis://{self.host}:{self.port}", decode_responses=True
            )
            self.sync_redis_client = Redis.from_url(
                f"redis://{self.host}:{self.port}", decode_responses=True
            )
            await self.aioredis_client.ping()
            self.sync_redis_client.ping()

            logger.info("Connected to Redis.")
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise e

    async def close(self):
        if self.aioredis_client:
            await self.aioredis_client.close()
        if self.sync_redis_client:
            self.sync_redis_client.close()

    async def async_subscribe(self, channels: Union[str, List[str]]) -> PubSub:
        """
        Subscribe to one or multiple channels asynchronously.

        Args:
            channels: A single channel name or a list of channel names
        Returns:
            PubSub: The subscription object
        """
        if not self.aioredis_client:
            raise RuntimeError("Redis client is not connected.")

        pubsub = self.aioredis_client.pubsub()

        if isinstance(channels, str):
            # Single channel
            await pubsub.subscribe(channels)
            logger.info(f"Subscribed to channel: {channels}")
        else:
            # Multiple channels
            await pubsub.subscribe(*channels)
            logger.info(f"Subscribed to channels: {', '.join(channels)}")

        return pubsub

    def sync_subscribe(self, channel: str) -> PubSub:
        if not self.sync_redis_client:
            raise RuntimeError("Redis client is not connected.")
        pubsub = self.sync_redis_client.pubsub()
        pubsub.subscribe(channel)
        return pubsub

    async def async_publish(self, channel: str, message: object):
        await self.aioredis_client.publish(channel, json.dumps(message))
        logger.info(f"Message published to channel '{channel}'.")

    def sync_publish(self, channel: str, message: object):
        self.sync_redis_client.publish(channel, json.dumps(message))
        logger.info(f"Message published to channel '{channel}'.")

    async def async_update_session_status(self, session_id: int, status: str, **kwargs):
        message = {
            "session_id": session_id,
            "status": status,
            "status_data": kwargs,
        }
        await self.async_publish(SESSION_STATUS_CHANNEL, message)

    def update_session_status(self, session_id: int, status: str, **kwargs):

        message = {
            "session_id": session_id,
            "status": status,
            "status_data": kwargs,
        }

        self.sync_publish(channel=SESSION_STATUS_CHANNEL, message=message)
