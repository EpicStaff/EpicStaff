import time
from collections.abc import Callable

from application.ports import AbstractRateLimiter
from loguru import logger
from redis.asyncio import Redis
from redis.exceptions import WatchError

# Each EXEC that beats ours is another holder taking a slot, so a few retries suffice; past them the caller retries later.
SLOT_ACQUIRE_ATTEMPTS = 10


class RedisRateLimiter(AbstractRateLimiter):
    """Fixed-window hit counters, and concurrency slots held as leases.

    A slot is a member of a sorted set scored by its lease expiry (unix seconds), so a holder that
    dies without releasing stops counting once its lease runs out instead of leaking the slot.
    """

    def __init__(self, redis: Redis, clock: Callable[[], float] = time.time):
        self._redis = redis
        self._clock = clock

    async def hit(self, key: str, limit: int, window_seconds: int) -> int | None:
        count = await self._redis.incr(key)
        ttl = await self._redis.ttl(key)
        if (
            ttl < 0
        ):  # no expiry (first hit, or a lost EXPIRE): restore it so the key cannot lock a client out forever
            await self._redis.expire(key, window_seconds)
            ttl = window_seconds
        if count <= limit:
            return None
        return max(1, ttl)

    async def acquire_slot(self, key: str, limit: int, holder: str, lease_seconds: int) -> bool:
        async with self._redis.pipeline() as pipe:
            for _ in range(SLOT_ACQUIRE_ATTEMPTS):
                try:
                    # WATCH makes count-then-add atomic: a concurrent change to the key aborts EXEC and we retry.
                    await pipe.watch(key)
                    now = self._clock()
                    if await pipe.zcount(key, f"({now}", "+inf") >= limit:
                        return False
                    pipe.multi()
                    pipe.zremrangebyscore(key, "-inf", now)
                    pipe.zadd(key, {holder: now + lease_seconds})
                    # The key outlives every lease in it, since each lease ends at most `lease_seconds` from now.
                    # This assumes every holder of the key uses the same lease length.
                    pipe.expire(key, lease_seconds)
                    await pipe.execute()
                    return True
                except WatchError:
                    continue
        return False

    async def renew_slot(self, key: str, holder: str, lease_seconds: int) -> None:
        async with self._redis.pipeline(transaction=True) as pipe:
            # XX: a lease pruned after it expired stays gone, since its slot may already be retaken.
            pipe.zadd(key, {holder: self._clock() + lease_seconds}, xx=True, ch=True)
            pipe.expire(key, lease_seconds)
            renewed, _ = await pipe.execute()
        if not renewed:
            logger.warning(
                "Stream slot lease {} on {} had expired; the stream no longer counts against the cap",
                holder,
                key,
            )

    async def release_slot(self, key: str, holder: str) -> None:
        await self._redis.zrem(key, holder)
