import os
import pathlib
import asyncio
from time import time
from asyncio.log import logger

from redis.asyncio import Redis

from src.shared.audit.export_jobs import EXPIRY_ZSET_KEY, JOB_KEY_PREFIX


def build_export_redis_client() -> Redis:
    return Redis(
        db=int(os.environ.get("AUDITOR_REDIS_DB", 1)),
        host=os.environ.get("REDIS_HOST", "localhost"),
        port=int(os.environ.get("REDIS_PORT", 6379)),
        password=os.environ.get("REDIS_PASSWORD"),
        decode_responses=True,
    )


class ExportCleanupService:
    def __init__(self, redis_client: Redis, sweep_interval_seconds: int = 60):
        self.redis_client = redis_client
        self.sweep_interval_seconds = sweep_interval_seconds
        self._task = None

    async def start(self):
        self._task = asyncio.create_task(self._sweep_loop())

    async def stop(self):
        if self._task:
            self._task.cancel()
            try:
                await self._task
                self._task = None
            except asyncio.CancelledError:
                pass

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
            await self._delete_job(job_id)

    async def _delete_job(self, job_id: str):
        key = f"{JOB_KEY_PREFIX}{job_id}"
        file_path = await self.redis_client.hget(key, "file_path")
        if file_path:
            pathlib.Path(file_path).unlink(missing_ok=True)
        async with self.redis_client.pipeline(transaction=True) as pipe:
            pipe.delete(key)
            pipe.zrem(EXPIRY_ZSET_KEY, job_id)
            await pipe.execute()
