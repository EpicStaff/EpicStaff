from enum import Enum
from time import time
from redis.asyncio import Redis

from src.shared.audit.export_jobs import JOB_KEY_PREFIX, EXPIRY_ZSET_KEY

JOB_HASH_TTL_SAFETY_MARGIN_SECONDS = 60 * 60 * 24


class JobStatus(str, Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"


class ExportJobService:
    def __init__(self, redis_client: Redis):
        self._redis = redis_client

    async def create_job(
        self, *, job_id: str, org_id: int, user_id: int, ttl_seconds: int, format: str
    ) -> None:
        now = time()
        expires_at = now + ttl_seconds
        key = f"{JOB_KEY_PREFIX}{job_id}"
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.hset(
                key,
                mapping={
                    "status": JobStatus.PENDING.value,
                    "org_id": org_id,
                    "user_id": user_id,
                    "created_at": now,
                    "expires_at": expires_at,
                    "file_path": "",
                    "format": format,
                },
            )
            pipe.expire(key, ttl_seconds + JOB_HASH_TTL_SAFETY_MARGIN_SECONDS)
            pipe.zadd(EXPIRY_ZSET_KEY, {job_id: expires_at})
            await pipe.execute()

    async def mark_done(self, job_id: str, file_path: str) -> bool:
        key = f"{JOB_KEY_PREFIX}{job_id}"
        if not await self._redis.exists(key):
            return False
        await self._redis.hset(
            key,
            mapping={"status": JobStatus.COMPLETED.value, "file_path": file_path},
        )
        return True

    async def mark_failed(self, job_id: str, error: str) -> bool:
        """Same "don't resurrect a deleted job" guard as mark_done - see there."""
        key = f"{JOB_KEY_PREFIX}{job_id}"
        if not await self._redis.exists(key):
            return False
        await self._redis.hset(
            key,
            mapping={"status": JobStatus.FAILED.value, "error": error},
        )
        return True

    async def get_job(self, job_id: str) -> dict | None:
        job = await self._redis.hgetall(f"{JOB_KEY_PREFIX}{job_id}")
        return job or None

    async def delete_job(self, job_id: str) -> None:
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.delete(f"{JOB_KEY_PREFIX}{job_id}")
            pipe.zrem(EXPIRY_ZSET_KEY, job_id)
            await pipe.execute()

    async def close(self) -> None:
        await self._redis.aclose()
