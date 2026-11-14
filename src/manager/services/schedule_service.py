import asyncio
import contextlib
import json
from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import settings
from apscheduler.events import EVENT_JOB_REMOVED
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
    on schedule_channel; Django's RedisPubSub routes it to ScheduleTriggerService.
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

        self.schedule_nodes: dict[int, str] = {}
        self._manual_removals: set[str] = set()
        self.listener_task: asyncio.Task | None = None

    async def start(self):
        """Subscribe to the Redis channel, load active schedules, start APScheduler.

        Subscribing first means a node update Django publishes while the DB
        load runs is buffered on the subscription instead of lost.
        """
        initial_pubsub = await self._subscribe_or_none()
        await self.load_schedules_from_django()
        self.scheduler.start()
        self.listener_task = asyncio.create_task(self._start_redis_listener(initial_pubsub))

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
        node_tz = self._resolve_tz(node.timezone)
        trigger = build_trigger(node, node_tz)

        if trigger is None:
            logger.warning(f"[ScheduleService] Could not build trigger for node {node_id}")
            return

        job_id = f"schedule_{node_id}"
        self.schedule_nodes[node_id] = job_id

        if node.run_mode == "once":
            self._manual_removals.add(job_id)
        else:
            self._manual_removals.discard(job_id)

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
        job_id = self.schedule_nodes.pop(node_id, None)
        if not job_id:
            logger.debug(f"[ScheduleService] No tracked job for node {node_id} (already removed)")
            return

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
        start = node.start_date_time
        if start.tzinfo is None:
            start = start.replace(tzinfo=UTC)
        return start <= datetime.now(UTC)

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
            # deactivate). These don't match the envelope schema and are
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
