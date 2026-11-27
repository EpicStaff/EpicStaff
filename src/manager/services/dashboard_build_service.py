from datetime import UTC, datetime, timedelta, tzinfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from helpers.logger import logger
from src.shared.redis_streams import (
    DASHBOARD_BUILD_REQUESTED_AT_FIELD,
    DASHBOARD_BUILD_STREAM,
    DASHBOARD_BUILD_STREAM_MAXLEN,
)

from services.redis_service import RedisService

DASHBOARD_BUILD_INTERVAL = timedelta(minutes=1)


class DashboardBuildService:
    def __init__(self, redis_service: RedisService, timezone: tzinfo):
        self.redis_service = redis_service
        self.scheduler = AsyncIOScheduler(timezone=timezone)
        self._trigger = IntervalTrigger(
            seconds=DASHBOARD_BUILD_INTERVAL.total_seconds(), timezone=timezone
        )

    async def start(self) -> None:
        self.scheduler.add_job(
            func=self.request_build,
            trigger=self._trigger,
            id="dashboard_build",
            name="DashboardBuild",
            replace_existing=True,
            max_instances=1,
            misfire_grace_time=60,
            coalesce=True,
        )
        self.scheduler.start()
        logger.info("DashboardBuildService scheduled (every {}).", DASHBOARD_BUILD_INTERVAL)

    async def request_build(self) -> None:
        try:
            await self.redis_service.async_stream_add(
                DASHBOARD_BUILD_STREAM,
                {DASHBOARD_BUILD_REQUESTED_AT_FIELD: datetime.now(UTC).isoformat()},
                maxlen=DASHBOARD_BUILD_STREAM_MAXLEN,
            )
        except Exception:
            logger.exception("DashboardBuild: failed to request build")

    def stop(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
