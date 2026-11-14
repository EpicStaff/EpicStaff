import asyncio
import contextlib
import json
from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import settings
from apscheduler.events import EVENT_JOB_MISSED, EVENT_JOB_REMOVED
from apscheduler.executors.asyncio import AsyncIOExecutor
from apscheduler.jobstores.base import JobLookupError
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from helpers.logger import logger
from pydantic import ValidationError
from repositories.schedule_trigger_repository import ScheduleTriggerNodeRepository
from src.shared.models import (
    ScheduleTriggerNodeDeletePayload,
    ScheduleTriggerNodePayload,
    ScheduleTriggerNodeUpdateMessage,
)
from src.shared.schedule.trigger_builder import build_trigger

from services.redis_service import RedisService


class ScheduleSyncError(Exception):
    """The active schedule nodes could not be read from the DB."""


class ScheduleService:
    """APScheduler-based scheduler.

    Fired schedules do not call Django via HTTP — they publish a Redis signal
    on schedule_channel ('run_session', 'deactivate', or 'missed' for a once-mode
    run that misfired); Django's RedisPubSub routes it to ScheduleTriggerService.
    """

    def __init__(self, redis_service: RedisService):
        self.redis_service = redis_service
        self.repository = ScheduleTriggerNodeRepository()
        self.tz = ZoneInfo(settings.TIMEZONE)

        self.scheduler = AsyncIOScheduler(
            jobstores={"default": MemoryJobStore()},
            executors={"default": AsyncIOExecutor()},
            job_defaults={
                "misfire_grace_time": 30,
                "coalesce": True,
            },
            timezone=self.tz,
        )
        self.scheduler.add_listener(self._on_job_removed, EVENT_JOB_REMOVED)
        self.scheduler.add_listener(self._on_job_missed, EVENT_JOB_MISSED)

        self.schedule_nodes: dict[int, str] = {}
        self._manual_removals: set[str] = set()
        # job_id -> node_id of registered once-mode jobs. EVENT_JOB_MISSED carries
        # only the job id, and by the time it is dispatched APScheduler has
        # already removed the job, so the node cannot be read from the job. An
        # entry left by a job that fired normally is harmless: a DateTrigger fires
        # once, so no missed event can follow; remove_schedule drops it later.
        self._once_jobs: dict[str, int] = {}
        # node_id -> scheduled_at of 'missed' signals Django has not acknowledged
        # yet. Pub/sub drops a message nobody listens to, and Django is often
        # still starting when the Manager reports misses right after its own
        # start, so the signal is repeated until the DB shows it was applied.
        self._pending_missed: dict[int, datetime] = {}
        # Nodes whose first republish was logged at INFO; later repeats of the
        # same miss go to DEBUG so a slow Django start does not flood the log.
        self._missed_republish_logged: set[int] = set()
        self.listener_task: asyncio.Task | None = None
        self.missed_retry_task: asyncio.Task | None = None

    async def start(self):
        """Subscribe to the Redis channel, load active schedules, start APScheduler.

        Subscribing first means a node update Django publishes while the DB
        load runs is buffered on the subscription instead of lost.
        """
        initial_pubsub = await self._subscribe_or_none()
        await self.load_schedules_from_django()
        self.scheduler.start()
        self.listener_task = asyncio.create_task(self._start_redis_listener(initial_pubsub))
        self.missed_retry_task = asyncio.create_task(self._retry_missed_until_acknowledged())

    async def _subscribe(self):
        pubsub = self.redis_service.aioredis_client.pubsub()
        try:
            await pubsub.subscribe(settings.SCHEDULE_CHANNEL)
        except BaseException:
            with contextlib.suppress(Exception):
                await pubsub.aclose()
            raise
        return pubsub

    async def _subscribe_or_none(self):
        try:
            return await self._subscribe()
        except Exception:
            # The listener retries the subscription and reconciles once it succeeds.
            logger.exception("[ScheduleService] Initial subscribe failed; the listener will retry")
            return None

    async def load_schedules_from_django(self):
        """Initial sync of active schedules from the DB into APScheduler.

        Retries indefinitely on DB error (repository returns None); an empty
        list is a valid terminal state (no active nodes).
        """
        attempt = 0
        while True:
            attempt += 1
            try:
                active_nodes = await self.repository.get_all_active_schedule_nodes()
                if active_nodes is None:
                    raise ScheduleSyncError("Could not read active schedule nodes from the DB")

                for node in active_nodes:
                    await self.add_schedule(node)

                logger.info(
                    f"[ScheduleService] DB sync completed "
                    f"(attempt {attempt}, nodes loaded: {len(active_nodes)})"
                )
                return
            except Exception as exc:
                logger.warning(
                    f"[ScheduleService] DB sync failed (attempt {attempt}): {exc}. "
                    f"Retrying in {settings.SYNC_RETRY_DELAY}s..."
                )
                await asyncio.sleep(settings.SYNC_RETRY_DELAY)

    async def add_schedule(self, node: ScheduleTriggerNodePayload):
        """Register (or replace) an APScheduler job for a schedule node."""
        node_id = node.id
        # A create or update from Django replaces the schedule a pending miss was about.
        self._drop_pending_missed(node_id)
        node_tz = self._resolve_tz(node.timezone)
        trigger = build_trigger(node, node_tz)

        if trigger is None:
            logger.warning(f"[ScheduleService] Could not build trigger for node {node_id}")
            return

        job_id = f"schedule_{node_id}"
        self.schedule_nodes[node_id] = job_id

        if node.run_mode == "once":
            self._manual_removals.add(job_id)
            self._once_jobs[job_id] = node_id
        else:
            self._manual_removals.discard(job_id)
            self._once_jobs.pop(job_id, None)

        try:
            self.scheduler.add_job(
                func=self.execute_schedule,
                trigger=trigger,
                id=job_id,
                args=[node],
                replace_existing=True,
                name=f"ScheduleNode-{node_id}",
            )
            logger.info(
                f"[ScheduleService] Job registered for node {node_id} "
                f"(trigger={type(trigger).__name__}, run_mode={node.run_mode}, "
                f"every={node.every}, unit={node.unit}, end_type={node.end_type})"
            )
        except Exception:
            logger.exception(f"[ScheduleService] Error registering Job for node {node_id}")
            self._manual_removals.discard(job_id)
            self._once_jobs.pop(job_id, None)
            # Reconcile reads "tracked but no job" as "once-node already fired", so a
            # node whose job was never registered must not stay tracked.
            if self.scheduler.get_job(job_id) is None:
                self.schedule_nodes.pop(node_id, None)

    def _on_job_removed(self, event):
        """APScheduler EVENT_JOB_REMOVED handler.

        Manual removals (remove_schedule, once-mode auto-remove) are pre-marked
        in _manual_removals and skipped. Other auto-removals (end_date reached
        on repeat triggers) publish 'deactivate' so Django flips is_active.
        """
        job_id = event.job_id

        if job_id in self._manual_removals:
            logger.debug(
                f"[ScheduleService] EVENT_JOB_REMOVED for {job_id}: pre-marked manual "
                f"(remove_schedule or once-mode auto-remove), skipping deactivate publish"
            )
            self._manual_removals.discard(job_id)
            return

        node_id = next(
            (nid for nid, jid in self.schedule_nodes.items() if jid == job_id),
            None,
        )
        if node_id is None:
            return

        self.schedule_nodes.pop(node_id, None)
        logger.info(
            f"[ScheduleService] Job {job_id} auto-removed by APScheduler "
            f"(end_date reached). Publishing 'deactivate' for node {node_id}."
        )
        asyncio.create_task(self._publish_deactivate(node_id))  # noqa: RUF006

    def _on_job_missed(self, event):
        """APScheduler EVENT_JOB_MISSED handler.

        A once-mode job whose run time passed more than misfire_grace_time ago
        (typically because the Manager was down at that moment) is skipped by
        APScheduler and removed, so execute_schedule never runs and never
        publishes 'deactivate'. Publish 'missed' instead so Django switches the
        node off and records the missed run. Missed ticks of repeat schedules
        are ignored: the schedule keeps running on its next tick.

        The node stays in schedule_nodes on purpose: _needs_reschedule must keep
        treating it as already fired until Django's node_update (is_active=False)
        arrives and remove_schedule cleans it up.
        """
        node_id = self._once_jobs.pop(event.job_id, None)
        if node_id is None:
            return

        scheduled_at = event.scheduled_run_time.astimezone(UTC)
        logger.warning(
            "[ScheduleService] Run of once-mode node {} scheduled at {} was missed (not "
            "started within the misfire grace time, e.g. the scheduler was down); "
            "switching the schedule off.",
            node_id,
            scheduled_at.isoformat(),
        )
        self._pending_missed[node_id] = scheduled_at
        self._missed_republish_logged.discard(node_id)
        asyncio.create_task(self._publish_missed(node_id, scheduled_at))  # noqa: RUF006

    async def _retry_missed_until_acknowledged(self):
        """Republish 'missed' signals until the DB shows Django acknowledged them.

        Checking PUBLISH's receiver count cannot tell whether Django got the
        signal: the Manager itself is subscribed to schedule_channel. The node's
        DB state is the acknowledgement instead: a node that is no longer an
        active once-mode schedule starting at the missed time was either
        switched off by Django or changed by the user, and needs no signal.
        Runs until cancelled; a failed tick is logged and retried on the next one.
        """
        while True:
            await asyncio.sleep(settings.SCHEDULE_LISTENER_RECONNECT_DELAY_SECONDS)
            if not self._pending_missed:
                continue
            try:
                await self._republish_unacknowledged_missed()
            except Exception:
                logger.exception("[ScheduleService] Retrying 'missed' signals failed")

    async def _republish_unacknowledged_missed(self):
        pending = dict(self._pending_missed)
        active_nodes = await self.repository.get_all_active_schedule_nodes()
        if active_nodes is None:
            logger.warning(
                "[ScheduleService] Could not read schedule nodes to check {} pending "
                "'missed' signal(s); retrying on the next tick",
                len(pending),
            )
            return

        active_nodes_by_id = {node.id: node for node in active_nodes}
        for node_id, scheduled_at in pending.items():
            # remove_schedule or add_schedule ran while this tick awaited: the
            # entry was acknowledged or superseded.
            if self._pending_missed.get(node_id) != scheduled_at:
                continue
            node = active_nodes_by_id.get(node_id)
            if node is None or not self._is_once_run_at(node, scheduled_at):
                self._drop_pending_missed(node_id)
                continue
            log_level = "DEBUG" if node_id in self._missed_republish_logged else "INFO"
            self._missed_republish_logged.add(node_id)
            logger.log(
                log_level,
                "[ScheduleService] Django has not applied the missed run of node {} "
                "scheduled at {} yet; republishing 'missed'",
                node_id,
                scheduled_at.isoformat(),
            )
            await self._publish_missed(node_id, scheduled_at)

    def _drop_pending_missed(self, node_id: int):
        self._pending_missed.pop(node_id, None)
        self._missed_republish_logged.discard(node_id)

    def _is_once_run_at(self, node: ScheduleTriggerNodePayload, scheduled_at: datetime) -> bool:
        return (
            node.run_mode == "once"
            and node.start_date_time is not None
            and self._as_utc(node.start_date_time) == scheduled_at
        )

    async def _publish_missed(self, node_id: int, scheduled_at: datetime):
        """Publish a 'missed' signal so Django deactivates the node and records the missed run."""
        try:
            await self.redis_service.async_publish(
                settings.SCHEDULE_CHANNEL,
                {
                    "action": "missed",
                    "node_id": node_id,
                    "scheduled_at": scheduled_at.isoformat(),
                },
            )
        except Exception:
            logger.exception("[ScheduleService] Error publishing 'missed' for node {}", node_id)

    async def _publish_deactivate(self, node_id: int):
        """Publish a 'deactivate' signal so Django flips is_active=False."""
        try:
            await self.redis_service.async_publish(
                settings.SCHEDULE_CHANNEL,
                {"action": "deactivate", "node_id": node_id},
            )
        except Exception:
            logger.exception(f"[ScheduleService] Error publishing 'deactivate' for node {node_id}")

    async def remove_schedule(self, node_id: int):
        """Remove the APScheduler job for a node (idempotent if already gone)."""
        # Django switched the node off or deleted it, which acknowledges a pending miss.
        self._drop_pending_missed(node_id)
        job_id = self.schedule_nodes.pop(node_id, None)
        if not job_id:
            logger.debug(f"[ScheduleService] No tracked job for node {node_id} (already removed)")
            return

        # A node switched off or deleted in Django must not later report a missed run.
        self._once_jobs.pop(job_id, None)
        self._manual_removals.add(job_id)
        try:
            self.scheduler.remove_job(job_id)
            logger.info(
                f"[ScheduleService] Job {job_id} removed (deactivate/delete signal from Django)"
            )
        except JobLookupError:
            logger.debug(f"[ScheduleService] Job {job_id} was already removed by APScheduler")
            self._manual_removals.discard(job_id)
        except Exception:
            logger.exception(f"[ScheduleService] Error removing Job {job_id}")
            self._manual_removals.discard(job_id)

    async def execute_schedule(self, node: ScheduleTriggerNodePayload):
        """APScheduler callback. Forward the fire event to Django via Redis.

        All business logic (guards, current_runs) lives Django-side in
        ScheduleTriggerService. For run_mode="once" also publishes 'deactivate'.
        A once-mode run that misfired never reaches here; _on_job_missed
        publishes 'missed' for it instead.
        """
        node_id = node.id
        logger.info(
            f"[ScheduleService] Executing schedule for node {node_id} "
            f"(run_mode={node.run_mode}, end_type={node.end_type})"
        )

        try:
            await self.redis_service.async_publish(
                settings.SCHEDULE_CHANNEL,
                {"action": "run_session", "node_id": node_id},
            )
            logger.info(f"[ScheduleService] Published 'run_session' for node {node_id}")

            if node.run_mode == "once":
                await self.redis_service.async_publish(
                    settings.SCHEDULE_CHANNEL,
                    {"action": "deactivate", "node_id": node_id},
                )
                logger.info(
                    f"[ScheduleService] Node {node_id} (once): published 'deactivate' "
                    f"(DateTrigger will auto-remove; listener pre-marked manual, "
                    f"will not publish duplicate)."
                )

            logger.info(f"[ScheduleService] Schedule fire complete for node {node_id}")
        except Exception:
            logger.exception(f"[ScheduleService] Error executing schedule for node {node_id}")

    def _resolve_tz(self, name: str | None):
        """Return a zoneinfo tz for the given IANA name, falling back to server tz."""
        if not name:
            return self.tz
        try:
            return ZoneInfo(name)
        except ZoneInfoNotFoundError:
            logger.warning(f"[ScheduleService] Unknown tz {name!r}, falling back to server tz")
            return self.tz

    async def _start_redis_listener(self, pubsub=None):
        """Apply live node updates from Django published on schedule_channel.

        Re-subscribes forever after any error. Pub/sub does not replay what was
        published while the subscription was down, so every re-subscribe is
        followed by a reconcile against the DB.

        Args:
            pubsub: Subscription opened before the initial DB load, so nothing
                published since then is lost. None means there was none, and the
                first subscription made here is reconciled.
        """
        missed_messages_possible = pubsub is None
        while True:
            try:
                if pubsub is None:
                    pubsub = await self._subscribe()
                # Reconcile only after subscribing, so an update published
                # during the reconcile is buffered on the subscription rather
                # than lost.
                if missed_messages_possible:
                    await self.reconcile_schedules_with_db()
                    missed_messages_possible = False

                async for message in pubsub.listen():
                    if message["type"] != "message":
                        continue
                    await self._handle_message(message["data"])
            except ScheduleSyncError as error:
                missed_messages_possible = True
                # The repository already logged the DB failure with its cause.
                logger.warning(
                    "[ScheduleService] Reconcile failed ({}), retrying in {} s",
                    error,
                    settings.SCHEDULE_LISTENER_RECONNECT_DELAY_SECONDS,
                )
                await asyncio.sleep(settings.SCHEDULE_LISTENER_RECONNECT_DELAY_SECONDS)
            except Exception:
                missed_messages_possible = True
                logger.exception(
                    "[ScheduleService] Redis listener failed, re-subscribing in {} s",
                    settings.SCHEDULE_LISTENER_RECONNECT_DELAY_SECONDS,
                )
                await asyncio.sleep(settings.SCHEDULE_LISTENER_RECONNECT_DELAY_SECONDS)
            finally:
                if pubsub is not None:
                    # The connection is usually already broken here; closing it
                    # only releases it, so a failure to close is not actionable.
                    with contextlib.suppress(Exception):
                        await pubsub.aclose()
                    pubsub = None

    async def reconcile_schedules_with_db(self):
        """Make the APScheduler jobs match the active schedule nodes in the DB.

        Removes jobs whose node is no longer active and adds or replaces jobs
        whose node is new or changed. Removals go through remove_schedule, so
        they are marked manual and never publish 'deactivate': the node is
        already inactive or deleted in Django.

        Raises:
            ScheduleSyncError: The DB could not be read; the jobs are left untouched.
        """
        active_nodes = await self.repository.get_all_active_schedule_nodes()
        if active_nodes is None:
            raise ScheduleSyncError("Could not read active schedule nodes from the DB")

        active_node_ids = {node.id for node in active_nodes}
        removed_node_ids = [
            node_id for node_id in list(self.schedule_nodes) if node_id not in active_node_ids
        ]
        for node_id in removed_node_ids:
            await self.remove_schedule(node_id)

        changed_nodes = [node for node in active_nodes if self._needs_reschedule(node)]
        for node in changed_nodes:
            await self.add_schedule(node)

        logger.info(
            "[ScheduleService] Reconciled with DB: {} active, {} removed, {} added or replaced",
            len(active_nodes),
            len(removed_node_ids),
            len(changed_nodes),
        )

    def _needs_reschedule(self, node: ScheduleTriggerNodePayload) -> bool:
        if (
            node.run_mode == "once"
            and node.id in self.schedule_nodes
            and self._once_start_has_passed(node)
        ):
            # Already scheduled here, so it has fired (or misfired) or is about
            # to: _on_job_removed keeps once-nodes in schedule_nodes after they
            # fire, and Django may not have processed their 'deactivate' yet.
            # Re-adding would fire it a second time inside the misfire grace.
            # A once-node never seen here (its create was lost) falls through
            # and is added; APScheduler's misfire grace decides whether it runs.
            return False

        job = self.scheduler.get_job(f"schedule_{node.id}")
        if job is None:
            return True
        # current_runs changes on every fire without changing the schedule;
        # replacing the job for it would only churn the trigger.
        scheduled_node: ScheduleTriggerNodePayload = job.args[0]
        return scheduled_node.model_dump(exclude={"current_runs"}) != node.model_dump(
            exclude={"current_runs"}
        )

    def _once_start_has_passed(self, node: ScheduleTriggerNodePayload) -> bool:
        if node.start_date_time is None:
            return False
        return self._as_utc(node.start_date_time) <= datetime.now(UTC)

    @staticmethod
    def _as_utc(moment: datetime) -> datetime:
        if moment.tzinfo is None:
            return moment.replace(tzinfo=UTC)
        return moment.astimezone(UTC)

    async def _handle_message(self, raw: bytes | str):
        """Validate one Redis message and dispatch on the inner action."""
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            logger.warning("[ScheduleService] Received invalid JSON message")
            return

        try:
            envelope = ScheduleTriggerNodeUpdateMessage.model_validate(parsed)
        except ValidationError:
            # Channel also carries non-node_update payloads (run_session,
            # deactivate, missed). These don't match the envelope schema and are
            # consumed by Django, not us — skip silently.
            return

        action = envelope.data.action
        node = envelope.data.node

        is_active = node.is_active if isinstance(node, ScheduleTriggerNodePayload) else None
        logger.info(
            f"[ScheduleService] Received '{action}' from Django for node {node.id} "
            f"(is_active={is_active})"
        )

        try:
            if action in ("create", "update"):
                assert isinstance(node, ScheduleTriggerNodePayload)
                if not node.is_active:
                    await self.remove_schedule(node.id)
                else:
                    await self.add_schedule(node)
            elif action == "delete":
                assert isinstance(node, ScheduleTriggerNodeDeletePayload)
                await self.remove_schedule(node.id)
        except Exception:
            logger.exception("[ScheduleService] Error processing Redis message")
