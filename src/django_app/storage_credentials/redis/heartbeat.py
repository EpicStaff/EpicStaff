import asyncio
from pathlib import Path
import redis.asyncio as aioredis
from loguru import logger

from storage_credentials.heartbeat_constants import (
    ISSUER_HEARTBEAT_FILE_PATH,
    ISSUER_HEARTBEAT_INTERVAL_SECONDS,
    ISSUER_HEARTBEAT_KEY_TTL_SECONDS,
)

from storage_credentials.redis.keys import ISSUER_HEARTBEAT_KEY


class IssuerHeartbeat:
    """Independent timer, not a per-cycle marker: confirms the event loop is
    alive and Redis is reachable by setting a short-TTL Redis key. On success
    it also touches a local file, which the Docker healthcheck probe reads
    instead of talking to Redis. Detects a blocked event loop or a dead
    process, not a coroutine hung on an await elsewhere in the process."""

    def __init__(
        self,
        *,
        redis_client: aioredis.Redis,
        heartbeat_file_path: str = ISSUER_HEARTBEAT_FILE_PATH,
    ):
        self._redis_client = redis_client
        self._heartbeat_file_path = heartbeat_file_path

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
            else:
                self._touch_heartbeat_file()
            await asyncio.sleep(ISSUER_HEARTBEAT_INTERVAL_SECONDS)

    def _touch_heartbeat_file(self) -> None:
        Path(self._heartbeat_file_path).touch()
