from datetime import tzinfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from helpers.logger import logger
from repositories.temp_storage_account_repository import TempStorageAccountRepository


class StorageAccountCleanupService:
    """Daily backstop cleanup of `storage_credentials_temp_account` rows
    whose owner (session/test-run/realtime chat) has finished.

    Housekeeping for the Postgres table only -- never calls MinIO/RustFS.
    Opportunistic deletion on revoke and FK CASCADE already remove most
    rows; this job only sweeps what they missed.
    """

    def __init__(
        self,
        repository: TempStorageAccountRepository,
        timezone: tzinfo,
        hour: int = 3,
        minute: int = 0,
    ):
        self.repository = repository
        self.scheduler = AsyncIOScheduler(timezone=timezone)
        self._trigger = CronTrigger(hour=hour, minute=minute, timezone=timezone)

    async def start(self, run_immediately: bool = True) -> None:
        self.scheduler.add_job(
            func=self.run_cleanup,
            trigger=self._trigger,
            id="storage_account_cleanup",
            name="StorageAccountCleanup",
            replace_existing=True,
            misfire_grace_time=3600,
            coalesce=True,
        )
        self.scheduler.start()
        logger.info("StorageAccountCleanupService scheduled (daily).")

        if run_immediately:
            await self.run_cleanup()

    async def run_cleanup(self) -> None:
        try:
            deleted = await self.repository.delete_finished_accounts()
            total = sum(deleted.values())
            if total:
                logger.info("StorageAccountCleanup: deleted {} row(s) ({})", total, deleted)
            else:
                logger.debug("StorageAccountCleanup: nothing to delete")
        except Exception as error:
            logger.error("StorageAccountCleanup: error during cleanup: {}", error)

    def stop(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
