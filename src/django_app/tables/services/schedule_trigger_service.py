import zoneinfo
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from django.db import transaction
from django.db.models import F
from django.utils import timezone
from loguru import logger
from src.shared.models import ScheduleTriggerNodePayload
from src.shared.schedule.trigger_builder import build_trigger
from tables.models.graph_models import ScheduleTriggerNode
from tables.services.run_admission import RunAdmissionRefusedError, log_trigger_refusal_once
from tables.services.schedule_condition_strategies import get_end_condition_strategy
from tables.services.trigger_spec import TriggerSpec
from tables.validators.schedule_trigger_validator import ScheduleTriggerValidator
from utils.singleton_meta import SingletonMeta

if TYPE_CHECKING:
    from tables.services.session_manager_service import SessionManagerService


# Fields that define when a schedule fires; changing one clears a recorded missed run.
_SCHEDULE_CONFIG_FIELDS = (
    "run_mode",
    "timezone",
    "start_date_time",
    "every",
    "unit",
    "weekdays",
    "end_type",
    "end_date_time",
    "max_runs",
)


class ScheduleTriggerService(metaclass=SingletonMeta):
    """Runs a graph session when a schedule fires (signalled from Manager via Redis)."""

    def __init__(
        self,
        session_manager_service: "SessionManagerService",
        validator: ScheduleTriggerValidator | None = None,
    ):
        self.session_manager_service = session_manager_service
        self.validator = validator or ScheduleTriggerValidator()

    def create_node(self, validated_data: dict) -> ScheduleTriggerNode:
        node = ScheduleTriggerNode.objects.create(**validated_data)
        next_run = self._compute_next_run_date_time(node)
        if next_run is not None:
            ScheduleTriggerNode.objects.filter(pk=node.pk).update(next_run_date_time=next_run)
            node.next_run_date_time = next_run
        return node

    @transaction.atomic
    def deactivate_node(self, node_id: int) -> None:
        """Flip is_active=False via .save() so post_save publishes node_update
        back to Manager — QuerySet.update() would skip the signal and leave
        Manager unaware via the standard update path.

        Manager repeats the signal for a repeat schedule, so a repeat node that
        has a fire time left again (the user extended it) treats it as stale.
        """
        node = ScheduleTriggerNode.objects.select_for_update().filter(id=node_id).first()
        if node is None:
            logger.warning(f"[ScheduleTriggerService] Node {node_id} not found for deactivation")
            return
        if not node.is_active:
            logger.info(f"[ScheduleTriggerService] Node {node_id} already inactive")
            return
        if node.run_mode == ScheduleTriggerNode.RunMode.REPEAT:
            next_run = self._compute_next_run_date_time(node)
            if next_run is not None:
                logger.info(
                    "[ScheduleTriggerService] Node {}: schedule has a fire time left ({}), "
                    "ignoring stale deactivate",
                    node_id,
                    next_run.isoformat(),
                )
                return
        node.is_active = False
        node.next_run_date_time = None
        node.save(update_fields=["is_active", "next_run_date_time", "updated_at"])
        logger.info(f"[ScheduleTriggerService] Node {node_id} deactivated")

    @transaction.atomic
    def mark_missed(self, node_id: int, scheduled_at: datetime) -> None:
        """Switch off a once-mode node whose run Manager missed, and record when it was due.

        Idempotent, since Manager repeats the signal; ignored when the node no longer
        starts at scheduled_at (the user changed it). Saves via .save() so post_save
        publishes node_update back to Manager.
        """
        node = ScheduleTriggerNode.objects.select_for_update().filter(id=node_id).first()
        if node is None:
            logger.warning(f"[ScheduleTriggerService] Node {node_id} not found for missed run")
            return
        if not node.is_active:
            logger.info(
                f"[ScheduleTriggerService] Node {node_id} already inactive, ignoring missed run"
            )
            return
        if (
            node.run_mode != ScheduleTriggerNode.RunMode.ONCE
            or node.start_date_time != scheduled_at
        ):
            logger.info(
                f"[ScheduleTriggerService] Node {node_id}: missed signal for {scheduled_at} "
                f"no longer matches the node's schedule, ignoring"
            )
            return
        node.is_active = False
        node.next_run_date_time = None
        node.missed_run_at = scheduled_at
        node.save(update_fields=["is_active", "next_run_date_time", "missed_run_at", "updated_at"])
        logger.info(
            f"[ScheduleTriggerService] Node {node_id}: run scheduled at {scheduled_at} "
            f"was missed, deactivated."
        )

    def update_node(
        self,
        instance: ScheduleTriggerNode,
        validated_data: dict,
    ) -> ScheduleTriggerNode:
        # Reactivating or changing the run cap restarts the run counter so the
        # node fires the full new quota instead of inheriting prior progress.
        reactivating = not instance.is_active and validated_data.get("is_active") is True
        new_max_runs = validated_data.get("max_runs", instance.max_runs)
        if reactivating or new_max_runs != instance.max_runs:
            validated_data["current_runs"] = 0
        if reactivating or self._schedule_config_changed(instance, validated_data):
            validated_data["missed_run_at"] = None

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        instance.next_run_date_time = self._compute_next_run_date_time(instance)
        instance.save()
        return instance

    @transaction.atomic
    def handle_schedule_trigger(self, node_id: int) -> None:
        """Check guards, start a graph session, and increment current_runs.

        select_for_update(skip_locked=True) lets concurrent workers race for the
        fired node; only one wins, others exit silently. current_runs is bumped
        via F() so concurrent increments never clobber each other.

        After a successful fire we recompute next_run_date_time and persist it
        via QuerySet.update() — this bypasses post_save on purpose, since
        Manager just fired this node and does not need its APScheduler job
        rebuilt for a derived-field change.

        A run refused at admission writes nothing and raises nothing: the refusal is
        logged once per node and cause, and the node keeps firing.

        Terminal conditions (end_date reached, max_runs reached) flip
        is_active=False AND next_run_date_time=None via .save() — the post_save
        signal publishes a node_update echo that Manager consumes to drop its
        APScheduler job. We intentionally do not publish 'deactivate' here to
        keep the channel's direction rule intact (Manager → Django only).
        """
        try:
            now = timezone.now()
            node = self._lock_active_node(node_id)
            if node is None:
                return

            strategy = get_end_condition_strategy(node.end_type)

            if strategy.is_end_date_passed(node, now):
                self._deactivate(node, f"end date {node.end_date_time} has passed")
                return

            if strategy.is_run_limit_reached(node):
                logger.info(
                    f"[ScheduleTriggerService] Node {node.id}: "
                    f"run limit reached ({node.current_runs}/{node.max_runs}). Skipping."
                )
                return

            try:
                self._start_session(node)
            except RunAdmissionRefusedError as error:
                # Each tick while refused is skipped and nothing about the node changes;
                # a one-time schedule that fires now does not run later.
                log_trigger_refusal_once(
                    trigger="schedule", node_id=node.pk, graph_id=node.graph_id, error=error
                )
                return
            self._increment_runs(node)

            if strategy.is_run_limit_reached(node):
                self._deactivate(
                    node,
                    f"max runs reached ({node.current_runs}/{node.max_runs})",
                )
                return

            next_run = self._compute_next_run_date_time(node, after=now + timedelta(microseconds=1))
            ScheduleTriggerNode.objects.filter(pk=node.pk).update(
                next_run_date_time=next_run,
                updated_at=timezone.now(),
            )

        except Exception as exc:
            logger.error(f"[ScheduleTriggerService] Error processing node {node_id}: {exc}")
            raise

    @staticmethod
    def _schedule_config_changed(instance: ScheduleTriggerNode, validated_data: dict) -> bool:
        return any(
            field in validated_data and validated_data[field] != getattr(instance, field)
            for field in _SCHEDULE_CONFIG_FIELDS
        )

    def _lock_active_node(self, node_id: int) -> ScheduleTriggerNode | None:
        node = (
            ScheduleTriggerNode.objects.select_for_update(skip_locked=True)
            .filter(id=node_id, is_active=True)
            .first()
        )
        if node is None:
            logger.warning(
                f"[ScheduleTriggerService] Node {node_id} not found, "
                f"inactive, or locked by another worker. Skipping."
            )
        return node

    def _start_session(self, node: ScheduleTriggerNode) -> None:
        self.session_manager_service.run_session(
            graph_id=node.graph_id,
            variables={},
            trigger=TriggerSpec.schedule(node),
        )
        logger.info(
            f"[ScheduleTriggerService] Session started for node {node.id} "
            f"(graph_id={node.graph_id})."
        )

    def _increment_runs(self, node: ScheduleTriggerNode) -> None:
        ScheduleTriggerNode.objects.filter(pk=node.pk).update(current_runs=F("current_runs") + 1)
        node.refresh_from_db()

    def _deactivate(self, node: ScheduleTriggerNode, reason: str) -> None:
        node.is_active = False
        node.next_run_date_time = None
        node.save(update_fields=["is_active", "next_run_date_time", "updated_at"])
        logger.info(f"[ScheduleTriggerService] Node {node.id}: {reason}, deactivated.")

    @staticmethod
    def _compute_next_run_date_time(
        node: ScheduleTriggerNode,
        after: datetime | None = None,
    ) -> datetime | None:
        """Return the next fire time as a UTC tz-aware datetime, or None.

        Single source of truth for `next_run_date_time`. Reads the node's
        *current in-memory state*, so callers must apply pending changes
        BEFORE calling this.

        Returns None when:
          - the node is not active, or schedule is not configured;
          - run quota is exhausted (current_runs >= max_runs);
          - APScheduler reports no future fire (end_date passed, once-mode in past).
        """
        if not node.is_active or not node.run_mode or not node.start_date_time:
            return None

        if node.max_runs is not None and node.current_runs >= node.max_runs:
            return None

        try:
            tz = zoneinfo.ZoneInfo(node.timezone or "UTC")
        except zoneinfo.ZoneInfoNotFoundError:
            tz = zoneinfo.ZoneInfo("UTC")

        payload = ScheduleTriggerNodePayload.model_validate(node)
        trigger = build_trigger(payload, tz)
        if trigger is None:
            return None

        after_utc = (after or datetime.now(UTC)).astimezone(UTC)
        nxt = trigger.get_next_fire_time(None, after_utc)
        return nxt.astimezone(UTC) if nxt else None
