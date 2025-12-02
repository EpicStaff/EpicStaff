import os
from loguru import logger
import redis.asyncio as aioredis
import json
from app.core.config import settings
from typing import Dict, Any, Optional

from app.request_models import WebhookEventData

class RedisService:
    """
    Handles all communication with the Redis server.
    """
    def __init__(self, host: str, port: int, webhook_channel: str):
        self.redis_url = f"redis://{host}:{port}"
        self.client = aioredis.from_url(self.redis_url, decode_responses=True)
        self.webhook_channel = webhook_channel
        logger.info(f"RedisService initialized for {self.redis_url}")

    async def publish_webhook(self, path: str, payload: Dict[str, Any]):
        """
        Modifies the data and publishes it to a Redis channel.
        """
        message_data = WebhookEventData(path=path, payload=payload)
                
        logger.debug(f"Publishing to Redis channel '{self.webhook_channel}'")
        await self.client.publish(self.webhook_channel, message_data.model_dump_json())

    async def close(self):
        """Closes the Redis connection."""
        logger.info("Closing Redis connection...")
        await self.client.close()



_redis_client: Optional[RedisService] = None

async def get_redis_service() -> RedisService:
    """FastAPI dependency to get the singleton RedisService."""
    global _redis_client
    WEBHOOK_MESSAGE_CHANNEL = os.environ.get("WEBHOOK_MESSAGE_CHANNEL", "webhooks")
    if _redis_client is None:
        _redis_client = RedisService(host=settings.REDIS_HOST, port=settings.REDIS_PORT, webhook_channel=WEBHOOK_MESSAGE_CHANNEL)
    return _redis_client

async def close_redis_connection():
    """Event handler to cleanly close the connection on shutdown."""
    global _redis_client
    if _redis_client:
        await _redis_client.close()
        _redis_client = None