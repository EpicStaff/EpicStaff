import asyncio
import json
import os
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apscheduler.events import EVENT_JOB_REMOVED
from apscheduler.executors.asyncio import AsyncIOExecutor
from apscheduler.jobstores.base import JobLookupError
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from pydantic import ValidationError

from helpers.logger import logger
from repositories.schedule_trigger_repository import ScheduleTriggerNodeRepository
from services.redis_service import RedisService
from src.shared.models import (
    ScheduleTriggerNodeDeletePayload,
    ScheduleTriggerNodePayload,
    ScheduleTriggerNodeUpdateMessage,
)
from src.shared.schedule.trigger_builder import build_trigger

import settings


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

    async def start(self):
        """Load active schedules, start APScheduler, subscribe to the Redis channel."""
        await self.load_schedules_from_django()
        self.scheduler.start()
        asyncio.create_task(self._start_redis_listener())

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
                    raise RuntimeError("Repository returned None (DB unreachable)")

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
            logger.warning(
                f"[ScheduleService] Could not build trigger for node {node_id}"
            )
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
            logger.exception(
                f"[ScheduleService] Error registering Job for node {node_id}"
            )
            self._manual_removals.discard(job_id)

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
        asyncio.create_task(self._publish_deactivate(node_id))

    async def _publish_deactivate(self, node_id: int):
        """Publish a 'deactivate' signal so Django flips is_active=False."""
        try:
            await self.redis_service.async_publish(
                settings.SCHEDULE_CHANNEL,
                {"action": "deactivate", "node_id": node_id},
            )
        except Exception:
            logger.exception(
                f"[ScheduleService] Error publishing 'deactivate' for node {node_id}"
            )

    async def remove_schedule(self, node_id: int):
        """Remove the APScheduler job for a node (idempotent if already gone)."""
        job_id = self.schedule_nodes.pop(node_id, None)
        if not job_id:
            logger.debug(
                f"[ScheduleService] No tracked job for node {node_id} (already removed)"
            )
            return

        self._manual_removals.add(job_id)
        try:
            self.scheduler.remove_job(job_id)
            logger.info(
                f"[ScheduleService] Job {job_id} removed "
                f"(deactivate/delete signal from Django)"
            )
        except JobLookupError:
            logger.debug(
                f"[ScheduleService] Job {job_id} was already removed by APScheduler"
            )
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
            logger.exception(
                f"[ScheduleService] Error executing schedule for node {node_id}"
            )

    def _resolve_tz(self, name: str | None):
        """Return a zoneinfo tz for the given IANA name, falling back to server tz."""
        if not name:
            return self.tz
        try:
            return ZoneInfo(name)
        except ZoneInfoNotFoundError:
            logger.warning(
                f"[ScheduleService] Unknown tz {name!r}, falling back to server tz"
            )
            return self.tz

    async def _start_redis_listener(self):
        """Subscribe to schedule_channel and apply live node updates from Django."""
        pubsub = self.redis_service.aioredis_client.pubsub()
        await pubsub.subscribe(settings.SCHEDULE_CHANNEL)

        try:
            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue
                await self._handle_message(message["data"])
        except Exception:
            logger.exception("[ScheduleService] Error in Redis listener")
        finally:
            await pubsub.unsubscribe(settings.SCHEDULE_CHANNEL)

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

        is_active = (
            node.is_active if isinstance(node, ScheduleTriggerNodePayload) else None
        )
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
