from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta, tzinfo
from functools import partial

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from helpers.chat_retention_client import ChatRetentionClient
from helpers.logger import logger
from repositories.retention_repository import RetentionInterruptedError, RetentionRepository
from src.shared.retention import DataType, RetentionPolicy, effective_retention_days


class RetentionService:
    """Nightly job deleting sessions and chat conversations older than their retention.

    For each organization the effective days are its own choice, or the instance default,
    clamped to the instance cap; 0 keeps the data forever. Sessions without a flow belong to
    no organization and follow the instance default. Conversations are purged by the chat
    service, and only when the chat is enabled. Audit events expire in the auditor, not here.

    Every organization and data type gets one log line with its count, also when the purge
    failed part-way, so deleted data always leaves a trace. One failure never stops the rest.
    """

    def __init__(
        self,
        repository: RetentionRepository,
        chat_client: ChatRetentionClient | None,
        policy: RetentionPolicy,
        timezone: tzinfo,
        hour: int = 3,
        minute: int = 30,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        self.repository = repository
        self.chat_client = chat_client
        self.policy = policy
        self.clock = clock
        self.scheduler = AsyncIOScheduler(timezone=timezone)
        self._trigger = CronTrigger(hour=hour, minute=minute, timezone=timezone)

    async def start(self) -> None:
        self.scheduler.add_job(
            func=self.run_retention,
            trigger=self._trigger,
            id="data_retention",
            name="DataRetention",
            replace_existing=True,
            misfire_grace_time=3600,
            coalesce=True,
        )
        self.scheduler.start()
        logger.info("RetentionService scheduled (daily).")

    def stop(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)

    async def run_retention(self) -> dict[str, int]:
        """Purge expired data of every organization once.

        Returns:
            Items deleted per data type, ``{"sessions": n, "conversations": m}``, including
            what a purge deleted before it failed.
        """
        now = self.clock()
        totals = {DataType.SESSIONS.value: 0, DataType.CONVERSATIONS.value: 0}
        try:
            organizations = await self.repository.list_org_retention()
        except Exception as error:
            # The org-less sessions below still expire; the organizations wait for tomorrow.
            logger.opt(exception=error).error(
                "Retention: could not read the organizations' retention: {}", error
            )
            organizations = []

        for organization in organizations:
            totals[DataType.SESSIONS.value] += await self._purge(
                DataType.SESSIONS,
                organization.org_id,
                organization.sessions_days,
                now,
                partial(self.repository.delete_expired_sessions, organization.org_id),
            )
            if self.chat_client is not None:
                totals[DataType.CONVERSATIONS.value] += await self._purge(
                    DataType.CONVERSATIONS,
                    organization.org_id,
                    organization.conversations_days,
                    now,
                    partial(self.chat_client.purge, organization.org_id),
                )
        totals[DataType.SESSIONS.value] += await self._purge(
            DataType.SESSIONS,
            None,
            None,
            now,
            partial(self.repository.delete_expired_sessions, None),
        )
        return totals

    async def _purge(
        self,
        data_type: DataType,
        org_id: int | None,
        chosen_days: int | None,
        now: datetime,
        purge: Callable[[datetime], Awaitable[int]],
    ) -> int:
        days = effective_retention_days(chosen_days, self.policy.rules[data_type])
        if days == 0:
            logger.info("Retention {} org={} days=0: kept forever", data_type.value, org_id)
            return 0
        cutoff = now - timedelta(days=days)
        try:
            deleted = await purge(cutoff)
        except RetentionInterruptedError as error:
            # A lock timeout lands here too: the rows are retried on the next run.
            logger.opt(exception=error).error(
                "Retention {} org={} days={}: deleted {} before failing: {}",
                data_type.value,
                org_id,
                days,
                error.deleted,
                error.__cause__,
            )
            return error.deleted
        except Exception as error:
            # One organization's failure must not keep the others' data past its retention.
            logger.opt(exception=error).error(
                "Retention {} org={} days={}: deleted 0, failed: {}",
                data_type.value,
                org_id,
                days,
                error,
            )
            return 0
        logger.info(
            "Retention {} org={} days={}: deleted {} older than {}",
            data_type.value,
            org_id,
            days,
            deleted,
            cutoff.isoformat(),
        )
        return deleted
