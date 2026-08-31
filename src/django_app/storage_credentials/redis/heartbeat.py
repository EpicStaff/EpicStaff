import asyncio

import redis.asyncio as aioredis
from loguru import logger

from storage_credentials.constants import (
    ISSUER_HEARTBEAT_INTERVAL_SECONDS,
    ISSUER_HEARTBEAT_KEY_TTL_SECONDS,
)
from storage_credentials.redis.keys import ISSUER_HEARTBEAT_KEY


class IssuerHeartbeat:
    """Writes a Redis key with a short TTL after each cycle, so the custom
    `/ht/` backend (`storage_credentials.health_checks`) can tell a hung or
    dead issuer process apart from a live one -- a `pgrep`-style liveness
    check would miss a process stuck looping on an error."""

    def __init__(self, *, redis_client: aioredis.Redis):
        self._redis_client = redis_client

    async def run_forever(self) -> None:
        while True:
            try:
                await self._redis_client.set(
                    ISSUER_HEARTBEAT_KEY, "1", ex=ISSUER_HEARTBEAT_KEY_TTL_SECONDS
                )
            except asyncio.CancelledError:
                raise
            except Exception as error:
                logger.error("IssuerHeartbeat: failed to write heartbeat: {}", error)
            await asyncio.sleep(ISSUER_HEARTBEAT_INTERVAL_SECONDS)
