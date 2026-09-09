import os
import pathlib
import asyncio
from time import time

from redis.asyncio import Redis

from helpers.logger import logger
from src.shared.audit.export_jobs import EXPIRY_ZSET_KEY, JOB_KEY_PREFIX, deregister_job


def build_export_redis_client() -> Redis:
    return Redis(
        db=int(os.environ.get("AUDITOR_REDIS_DB", 1)),
        host=os.environ.get("REDIS_HOST", "localhost"),
        port=int(os.environ.get("REDIS_PORT", 6379)),
        password=os.environ.get("REDIS_PASSWORD") or None,
        decode_responses=True,
    )


class ExportCleanupService:
    def __init__(
        self,
        redis_client: Redis,
        sweep_interval_seconds: int = 60,
        export_data_dir: str | None = None,
    ):
        self.redis_client = redis_client
        self.sweep_interval_seconds = sweep_interval_seconds
        self.export_data_dir = export_data_dir
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
                logger.error(f"Error occurred while sweeping exports: {e}")
            await asyncio.sleep(self.sweep_interval_seconds)

    async def sweep_once(self):
        due_jobs_ids = await self.redis_client.zrangebyscore(
            EXPIRY_ZSET_KEY, min=0, max=time()
        )
        for job_id in due_jobs_ids:
            try:
                await self._delete_job(job_id)
            except Exception as e:
                logger.error(f"Error deleting export job {job_id}: {e}")

    async def _delete_job(self, job_id: str):
        key = f"{JOB_KEY_PREFIX}{job_id}"
        file_path, org_id, user_id = await self.redis_client.hmget(
            key, "file_path", "org_id", "user_id"
        )

        if org_id is None or user_id is None:
            logger.warning(
                f"Job {job_id} hash missing during sweep; skipping index cleanup"
            )
            await self.redis_client.zrem(EXPIRY_ZSET_KEY, job_id)
            return

        if file_path:
            pathlib.Path(file_path).unlink(missing_ok=True)
        elif self.export_data_dir:
            for stale_file in pathlib.Path(self.export_data_dir).glob(f"{job_id}.*"):
                stale_file.unlink(missing_ok=True)
        async with self.redis_client.pipeline(transaction=True) as pipe:
            deregister_job(pipe, job_id=job_id, org_id=org_id, user_id=user_id)
            await pipe.execute()
