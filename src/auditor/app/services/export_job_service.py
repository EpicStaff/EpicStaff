from collections.abc import Iterable
from enum import StrEnum
from time import time

from redis.asyncio import Redis
from src.shared.audit.export_jobs import (
    JOB_KEY_PREFIX,
    deregister_job,
    register_job,
    user_jobs_key,
)

JOB_HASH_TTL_SAFETY_MARGIN_SECONDS = 60 * 60 * 24


class JobStatus(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"


class ExportJobService:
    def __init__(self, redis_client: Redis):
        self._redis = redis_client

    async def create_job(
        self,
        *,
        domain: str,
        job_id: str,
        org_id: int,
        user_id: int,
        ttl_seconds: int,
        format: str,
    ) -> None:
        now = time()
        expires_at = now + ttl_seconds
        mapping = {
            "domain": domain,
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
                domain=domain,
                job_id=job_id,
                org_id=org_id,
                user_id=user_id,
                mapping=mapping,
                hash_ttl_seconds=ttl_seconds + JOB_HASH_TTL_SAFETY_MARGIN_SECONDS,
                expires_at=expires_at,
            )
            await pipe.execute()

    async def mark_done(self, job_id: str, file_path: str, truncated: bool) -> bool:
        return await self._update_existing_job(
            job_id,
            {
                "status": JobStatus.COMPLETED.value,
                "file_path": file_path,
                "truncated": str(truncated),
            },
        )

    async def mark_failed(self, job_id: str) -> bool:
        return await self._update_existing_job(job_id, {"status": JobStatus.FAILED.value})

    async def _update_existing_job(self, job_id: str, mapping: dict) -> bool:
        """Writes `mapping` only if the job hash still exists, atomically: the
        hash is WATCHed, so a delete (manual or the manager's sweep) landing
        between the existence check and the write aborts the write instead of
        recreating the hash with no TTL and an orphaned export file. Returns
        whether the write happened."""
        key = f"{JOB_KEY_PREFIX}{job_id}"

        async def _write_if_present(pipe) -> bool:
            if not await pipe.exists(key):
                return False
            pipe.multi()
            pipe.hset(key, mapping=mapping)
            return True

        return await self._redis.transaction(_write_if_present, key, value_from_callable=True)

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
            {"job_id": job_id} | job for job_id, job in zip(job_ids, results, strict=True) if job
        ]

    async def get_jobs_by_user(self, domain: str, org_id: int, user_id: int) -> list[dict]:
        key = user_jobs_key(domain, org_id, user_id)
        job_ids = await self._redis.smembers(key)
        jobs = await self.get_jobs(job_ids)
        return jobs

    async def delete_job(self, job_id: str, org_id: int, user_id: int, domain: str) -> None:
        async with self._redis.pipeline(transaction=True) as pipe:
            deregister_job(pipe, domain=domain, job_id=job_id, org_id=org_id, user_id=user_id)
            await pipe.execute()

    async def close(self) -> None:
        await self._redis.aclose()
