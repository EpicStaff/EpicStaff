from types import ModuleType

from redis.asyncio import Redis
from loguru import logger


def build_redis_client(settings: ModuleType) -> Redis:
    """
    Construct a new Redis client from settings.

    Call this once, during app startup (lifespan) - not per-request, and not
    at import time. Ownership of the single instance for the app's lifetime
    belongs to app.state via the repository factory, not this function.
    """
    logger.info(f"Connecting to Redis at {settings.REDIS_HOST}:{settings.REDIS_PORT}")
    return Redis(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        password=settings.REDIS_PASSWORD,
        db=settings.AUDITOR_REDIS_DB,
        decode_responses=True,
    )
