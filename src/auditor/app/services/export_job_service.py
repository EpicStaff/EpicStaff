from enum import Enum
from time import time
from redis.asyncio import Redis

from shared.audit.export_jobs import JOB_KEY_PREFIX, EXPIRY_ZSET_KEY

JOB_HASH_TTL_BACKSTOP = 60 * 60 * 24 * 7


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
            pipe.expire(key, JOB_HASH_TTL_BACKSTOP)
            pipe.zadd(EXPIRY_ZSET_KEY, {job_id: expires_at})
            await pipe.execute()

    async def mark_done(self, job_id, file_path: str) -> None:
        await self._redis.hset(
            f"{JOB_KEY_PREFIX}{job_id}",
            mapping={"status": JobStatus.COMPLETED.value, "file_path": file_path},
        )

    async def mark_failed(self, job_id, error: str) -> None:
        await self._redis.hset(
            f"{JOB_KEY_PREFIX}{job_id}",
            mapping={"status": JobStatus.FAILED.value, "error": error},
        )

    async def get_job(self, job_id: str) -> dict | None:
        job = await self._redis.hgetall(f"{JOB_KEY_PREFIX}{job_id}")
        return job or None

    async def delete_job(self, job_id: str) -> None:
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.delete(f"{JOB_KEY_PREFIX}{job_id}")
            pipe.zrem(EXPIRY_ZSET_KEY, job_id)
            await pipe.execute()

    async def close(self) -> None:
        await self._redis.close()
