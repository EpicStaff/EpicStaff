import asyncio
import pathlib
import uuid
from time import time

from redis.asyncio import Redis

import settings
from helpers.logger import logger
from src.shared.audit.export_jobs import EXPIRY_ZSET_KEY, JOB_KEY_PREFIX, deregister_job


def build_export_redis_client() -> Redis:
    return Redis(
        db=settings.AUDITOR_REDIS_DB,
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        username=settings.REDIS_USER,
        password=settings.REDIS_PASSWORD,
        decode_responses=True,
    )


def _is_canonical_uuid(value: str) -> bool:
    try:
        return str(uuid.UUID(value)) == value
    except ValueError:
        return False


class ExportCleanupService:
    """Delete expired audit export files and their Redis job records.

    Job ids and file paths come from Redis, which other containers can write
    to, so they are treated as untrusted: a file is only ever unlinked when it
    resolves inside export_data_dir, and a job id is only used in a glob
    pattern once it parses as a UUID.
    """

    def __init__(
        self,
        redis_client: Redis,
        export_data_dir: str,
        sweep_interval_seconds: int = 60,
    ):
        self.redis_client = redis_client
        self.sweep_interval_seconds = sweep_interval_seconds
        self.export_data_dir = pathlib.Path(export_data_dir).resolve()
        self._task = None

    async def start(self):
        self._task = asyncio.create_task(self._sweep_loop())

    async def stop(self):
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _sweep_loop(self):
        while True:
            try:
                await self.sweep_once()
            except Exception as e:
                logger.error("Error occurred while sweeping exports: {}", e)
            await asyncio.sleep(self.sweep_interval_seconds)

    async def sweep_once(self):
        due_jobs_ids = await self.redis_client.zrangebyscore(
            EXPIRY_ZSET_KEY, min=0, max=time()
        )
        for job_id in due_jobs_ids:
            try:
                await self._delete_job(job_id)
            except Exception as e:
                logger.error("Error deleting export job {}: {}", job_id, e)

    def _unlink_inside_export_dir(self, job_id: str, candidate: pathlib.Path) -> None:
        resolved = candidate.resolve()
        if not resolved.is_relative_to(self.export_data_dir):
            logger.warning(
                "Refusing to delete {} for export job {}: outside export dir {}",
                resolved,
                job_id,
                self.export_data_dir,
            )
            return
        resolved.unlink(missing_ok=True)

    async def _delete_job(self, job_id: str):
        key = f"{JOB_KEY_PREFIX}{job_id}"
        file_path, org_id, user_id, domain = await self.redis_client.hmget(
            key, "file_path", "org_id", "user_id", "domain"
        )

        if file_path:
            self._unlink_inside_export_dir(job_id, pathlib.Path(file_path))
        elif _is_canonical_uuid(job_id):
            for stale_file in self.export_data_dir.glob(f"{job_id}.*"):
                self._unlink_inside_export_dir(job_id, stale_file)
        else:
            logger.warning(
                "Export job id {!r} is not a UUID; skipping file cleanup, "
                "deregistering its Redis entry only",
                job_id,
            )

        if org_id is None or user_id is None or domain is None:
            logger.warning(
                "Job {} hash missing or incomplete during sweep; file "
                "cleaned up but its per-user index entry may be left orphaned",
                job_id,
            )
            await self.redis_client.zrem(EXPIRY_ZSET_KEY, job_id)
            return

        async with self.redis_client.pipeline(transaction=True) as pipe:
            deregister_job(
                pipe, domain=domain, job_id=job_id, org_id=org_id, user_id=user_id
            )
            await pipe.execute()
