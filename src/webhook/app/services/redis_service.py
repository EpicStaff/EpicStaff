from typing import Any

import redis.asyncio as aioredis
from loguru import logger
from redis.client import PubSub
from src.shared.models import WebhookEventData

from app.core.settings import settings


class NoWebhookSubscriberError(Exception):
    """Raised when a webhook event was published but no listener received it."""

    def __init__(self, channel: str):
        self.channel = channel
        super().__init__(f"No subscriber on Redis channel '{channel}'; webhook event was dropped.")


class RedisService:
    """
    Handles all communication with the Redis server.
    """

    def __init__(self, host: str, port: int, webhook_channel: str, password: str):
        self.redis_url = f"redis://{host}:{port}"
        self.client = aioredis.from_url(self.redis_url, password=password, decode_responses=True)
        self.webhook_channel = webhook_channel
        logger.info(f"RedisService initialized for {self.redis_url}")

    async def publish_webhook(
        self,
        path: str,
        payload: dict[str, Any],
        config_id: str | None = None,
    ) -> None:
        """Publish a webhook event to the channel Django's `listen_redis` worker reads.

        Redis pub/sub does not keep messages: one published while no listener is
        subscribed (Django restarting, listener process down) is gone. Raising lets the
        caller reject the request so the sender retries instead of the event vanishing.

        Raises:
            NoWebhookSubscriberError: The publish reached no subscriber.
        """
        message_data = WebhookEventData(
            path=path,
            payload=payload,
            config_id=config_id,
        )

        logger.debug(f"Publishing to Redis channel '{self.webhook_channel}'")
        receiver_count = await self.client.publish(
            self.webhook_channel, message_data.model_dump_json()
        )
        if receiver_count == 0:
            raise NoWebhookSubscriberError(self.webhook_channel)

    async def set_tunnel_url(self, unique_id: str, url: str) -> None:
        await self.client.hset(settings.TUNNEL_URLS_HASH_KEY, unique_id, url)
        logger.debug(f"Stored tunnel URL for '{unique_id}': {url}")

    async def delete_tunnel_url(self, unique_id: str) -> None:
        await self.client.hdel(settings.TUNNEL_URLS_HASH_KEY, unique_id)
        logger.debug(f"Removed tunnel URL for '{unique_id}'")

    async def close(self):
        """Closes the Redis connection."""
        logger.info("Closing Redis connection...")
        await self.client.close()

    async def async_subscribe(self, channel: str) -> PubSub:
        pubsub = self.client.pubsub()
        await pubsub.subscribe(channel)
        return pubsub


_redis_service: RedisService | None = None


async def get_redis_service() -> RedisService:
    """FastAPI dependency to get the singleton RedisService."""
    global _redis_service
    if _redis_service is None:
        _redis_service = RedisService(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            password=settings.REDIS_PASSWORD,
            webhook_channel=settings.WEBHOOK_MESSAGE_CHANNEL,
        )

    return _redis_service


async def close_redis_connection():
    """Event handler to cleanly close the connection on shutdown."""
    global _redis_service
    if _redis_service:
        await _redis_service.close()
        _redis_service = None
