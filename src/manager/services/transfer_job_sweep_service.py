"""Periodic request for django_app's transfer-job sweep.

``request_transfer_job_sweep`` is scheduler-agnostic: it takes its Redis service as an
argument and knows nothing about APScheduler, so a Celery task or beat entry can call it
directly. ``TransferJobSweepService`` is only the APScheduler wiring around it.
"""

from datetime import UTC, datetime, timedelta, tzinfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from helpers.logger import logger
from src.shared.redis_streams import (
    TRANSFER_JOB_STREAM,
    TRANSFER_JOB_STREAM_MAXLEN,
    TRANSFER_JOB_SWEEP_REQUESTED_AT_FIELD,
)

from services.redis_service import RedisService

TRANSFER_JOB_SWEEP_INTERVAL = timedelta(minutes=15)


async def request_transfer_job_sweep(redis_service: RedisService) -> None:
    """Add one sweep request to the transfer-job Redis stream.

    Manager has no ORM or object-storage access, so it only asks; one django_app
    consumer reads the request through a consumer group and deletes expired jobs and
    their archives and fails stale ones, so the sweep runs once per deployment however
    many django_app containers there are. Safe to call any number of times: the sweep
    itself is idempotent and the stream is capped.

    Raises whatever the Redis call raises, so a caller with retries (a Celery task) can
    retry; ``TransferJobSweepService`` logs the error instead to keep its scheduler running.
    """
    await redis_service.async_stream_add(
        TRANSFER_JOB_STREAM,
        {TRANSFER_JOB_SWEEP_REQUESTED_AT_FIELD: datetime.now(UTC).isoformat()},
        maxlen=TRANSFER_JOB_STREAM_MAXLEN,
    )
    logger.info("TransferJobSweep: sweep requested")


class TransferJobSweepService:
    """Call ``request_transfer_job_sweep`` on a fixed interval with APScheduler."""

    def __init__(
        self,
        redis_service: RedisService,
        timezone: tzinfo,
        interval: timedelta = TRANSFER_JOB_SWEEP_INTERVAL,
    ):
        self.redis_service = redis_service
        self.scheduler = AsyncIOScheduler(timezone=timezone)
        self._trigger = IntervalTrigger(seconds=interval.total_seconds(), timezone=timezone)

    async def start(self) -> None:
        """Schedule the periodic sweep request; nothing is requested until the first fire."""
        self.scheduler.add_job(
            func=self._request_sweep_logging_errors,
            trigger=self._trigger,
            id="transfer_job_sweep",
            name="TransferJobSweep",
            replace_existing=True,
            max_instances=1,
            # A fire delayed past this is dropped; the next interval sweeps anyway.
            misfire_grace_time=300,
            coalesce=True,
        )
        self.scheduler.start()
        logger.info("TransferJobSweepService scheduled (every {}).", self._trigger.interval)

    async def _request_sweep_logging_errors(self) -> None:
        # APScheduler would catch the error too, but log it through stdlib logging, which
        # bypasses loguru; log it here instead. The next fire retries.
        try:
            await request_transfer_job_sweep(self.redis_service)
        except Exception:
            logger.exception("TransferJobSweep: failed to request sweep")

    def stop(self) -> None:
        """Stop the scheduler without waiting for a running job."""
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
