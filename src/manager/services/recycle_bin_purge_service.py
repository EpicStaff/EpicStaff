from datetime import UTC, datetime, tzinfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from helpers.logger import logger
from src.shared.redis_streams import (
    RECYCLE_BIN_PURGE_JOB_FIELD,
    RECYCLE_BIN_PURGE_REQUESTED_AT_FIELD,
    RECYCLE_BIN_PURGE_STREAM,
    RECYCLE_BIN_PURGE_STREAM_MAXLEN,
    STORAGE_MEASUREMENT_JOB,
)

from services.redis_service import RedisService


class RecycleBinPurgeService:
    """Clock for the storage maintenance jobs: the daily recycle-bin purge and the hourly
    storage measurement.

    Manager has no ORM, object-storage or GraphRAG access, so it only adds a request
    to a Redis stream. One django_app consumer reads it through a consumer group and
    runs the job, which makes each job run once per deployment however many
    django_app containers there are.
    """

    def __init__(
        self,
        redis_service: RedisService,
        timezone: tzinfo,
        hour: int = 3,
        minute: int = 0,
    ):
        self.redis_service = redis_service
        self.scheduler = AsyncIOScheduler(timezone=timezone)
        self._trigger = CronTrigger(hour=hour, minute=minute, timezone=timezone)
        self._measurement_trigger = CronTrigger(minute=minute, timezone=timezone)

    async def start(self) -> None:
        """Schedule the daily purge and hourly measurement requests; nothing is requested
        until the first fire."""
        self.scheduler.add_job(
            func=self.request_purge,
            trigger=self._trigger,
            id="recycle_bin_purge",
            name="RecycleBinPurge",
            replace_existing=True,
            max_instances=1,
            misfire_grace_time=3600,
            coalesce=True,
        )
        self.scheduler.add_job(
            func=self.request_storage_measurement,
            trigger=self._measurement_trigger,
            id="storage_measurement",
            name="StorageMeasurement",
            replace_existing=True,
            max_instances=1,
            misfire_grace_time=600,
            coalesce=True,
        )
        self.scheduler.start()
        logger.info("RecycleBinPurgeService scheduled (purge daily, measurement hourly).")

    async def request_purge(self) -> None:
        """Add one purge request to the Redis stream.

        Swallows and logs errors so the scheduler keeps running; tomorrow's fire retries.
        """
        try:
            await self.redis_service.async_stream_add(
                RECYCLE_BIN_PURGE_STREAM,
                {RECYCLE_BIN_PURGE_REQUESTED_AT_FIELD: datetime.now(UTC).isoformat()},
                maxlen=RECYCLE_BIN_PURGE_STREAM_MAXLEN,
            )
            logger.info("RecycleBinPurge: purge requested")
        except Exception:
            logger.exception("RecycleBinPurge: failed to request purge")

    async def request_storage_measurement(self) -> None:
        """Add one storage measurement request to the Redis stream.

        Swallows and logs errors so the scheduler keeps running; the next hour's fire retries.
        """
        try:
            await self.redis_service.async_stream_add(
                RECYCLE_BIN_PURGE_STREAM,
                {
                    RECYCLE_BIN_PURGE_REQUESTED_AT_FIELD: datetime.now(UTC).isoformat(),
                    RECYCLE_BIN_PURGE_JOB_FIELD: STORAGE_MEASUREMENT_JOB,
                },
                maxlen=RECYCLE_BIN_PURGE_STREAM_MAXLEN,
            )
            logger.info("StorageMeasurement: measurement requested")
        except Exception:
            logger.exception("StorageMeasurement: failed to request measurement")

    def stop(self) -> None:
        """Stop the scheduler without waiting for a running job."""
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
