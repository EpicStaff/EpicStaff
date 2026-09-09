from enum import Enum
from time import time
from typing import Iterable

from redis.asyncio import Redis

from src.shared.audit.export_jobs import (
    JOB_KEY_PREFIX,
    register_job,
    deregister_job,
    user_jobs_key,
)

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
        mapping = {
            "status": JobStatus.PENDING.value,
            "org_id": org_id,
            "user_id": user_id,
            "created_at": now,
            "expires_at": expires_at,
            "file_path": "",
            "format": format,
        }
        async with self._redis.pipeline(transaction=True) as pipe:
            register_job(
                pipe,
                job_id=job_id,
                org_id=org_id,
                user_id=user_id,
                mapping=mapping,
                hash_ttl_seconds=ttl_seconds + JOB_HASH_TTL_SAFETY_MARGIN_SECONDS,
                expires_at=expires_at,
            )
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

    async def get_jobs(self, job_ids: Iterable[str]) -> list[dict]:
        job_ids = list(job_ids)
        if not job_ids:
            return []

        async with self._redis.pipeline(transaction=False) as pipe:
            for job_id in job_ids:
                pipe.hgetall(f"{JOB_KEY_PREFIX}{job_id}")
            results = await pipe.execute()

        return [
            {"job_id": job_id} | job for job_id, job in zip(job_ids, results) if job
        ]

    async def get_jobs_by_user(self, org_id: int, user_id: int) -> list[dict]:
        key = user_jobs_key(org_id, user_id)
        job_ids = await self._redis.smembers(key)
        jobs = await self.get_jobs(job_ids)
        return jobs

    async def delete_job(self, job_id: str, org_id: int, user_id: int) -> None:
        async with self._redis.pipeline(transaction=True) as pipe:
            deregister_job(pipe, job_id=job_id, org_id=org_id, user_id=user_id)
            await pipe.execute()

    async def close(self) -> None:
        await self._redis.aclose()
