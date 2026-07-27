import zoneinfo
from datetime import datetime, timedelta, timezone as _tz
from typing import TYPE_CHECKING

from django.db import transaction
from django.db.models import F
from django.utils import timezone
from loguru import logger

from src.shared.models import ScheduleTriggerNodePayload
from src.shared.schedule.trigger_builder import build_trigger
from tables.models.graph_models import ScheduleTriggerNode
from tables.services.schedule_condition_strategies import get_end_condition_strategy
from tables.validators.schedule_trigger_validator import ScheduleTriggerValidator
from utils.singleton_meta import SingletonMeta
from utils.graph_utils import generate_node_name

if TYPE_CHECKING:
    from tables.services.session_manager_service import SessionManagerService


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
            ScheduleTriggerNode.objects.filter(pk=node.pk).update(
                next_run_date_time=next_run
            )
            node.next_run_date_time = next_run
        return node

    def deactivate_node(self, node_id: int) -> None:
        """Flip is_active=False via .save() so post_save publishes node_update
        back to Manager — QuerySet.update() would skip the signal and leave
        Manager unaware via the standard update path.
        """
        node = ScheduleTriggerNode.objects.filter(id=node_id).first()
        if node is None:
            logger.warning(
                f"[ScheduleTriggerService] Node {node_id} not found for deactivation"
            )
            return
        if not node.is_active:
            logger.info(f"[ScheduleTriggerService] Node {node_id} already inactive")
            return
        self._persist_deactivation(node)
        logger.info(f"[ScheduleTriggerService] Node {node_id} deactivated")

    def update_node(
        self,
        instance: ScheduleTriggerNode,
        validated_data: dict,
    ) -> ScheduleTriggerNode:
        # Reactivating or changing the run cap restarts the run counter so the
        # node fires the full new quota instead of inheriting prior progress.
        reactivating = (
            not instance.is_active and validated_data.get("is_active") is True
        )
        new_max_runs = validated_data.get("max_runs", instance.max_runs)
        if reactivating or new_max_runs != instance.max_runs:
            validated_data["current_runs"] = 0

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

            self._start_session(node)
            self._increment_runs(node)

            if strategy.is_run_limit_reached(node):
                self._deactivate(
                    node,
                    f"max runs reached ({node.current_runs}/{node.max_runs})",
                )
                return

            next_run = self._compute_next_run_date_time(
                node, after=now + timedelta(microseconds=1)
            )
            ScheduleTriggerNode.objects.filter(pk=node.pk).update(
                next_run_date_time=next_run,
                updated_at=timezone.now(),
            )

        except Exception as exc:
            logger.error(
                f"[ScheduleTriggerService] Error processing node {node_id}: {exc}"
            )
            raise

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
            entrypoint=generate_node_name(node.id, node.node_name),
        )
        logger.info(
            f"[ScheduleTriggerService] Session started for node {node.id} "
            f"(graph_id={node.graph_id})."
        )

    def _increment_runs(self, node: ScheduleTriggerNode) -> None:
        ScheduleTriggerNode.objects.filter(pk=node.pk).update(
            current_runs=F("current_runs") + 1
        )
        node.refresh_from_db()

    def _deactivate(self, node: ScheduleTriggerNode, reason: str) -> None:
        self._persist_deactivation(node)
        logger.info(f"[ScheduleTriggerService] Node {node.id}: {reason}, deactivated.")

    def _persist_deactivation(self, node: ScheduleTriggerNode) -> None:
        """Flip is_active=False via .save() (unconditional, DB stays
        authoritative), then notify any live collaborative session so its
        Redis snapshot's content_hash doesn't fall out of sync with the row
        this write just produced.

        Uses ``transaction.on_commit`` rather than notifying immediately:
        both call sites persist inside a transaction (``handle_schedule_trigger``
        is ``@transaction.atomic``), and the notified consumer refreshes
        content_hash by reading this row from the DB — notifying before
        commit could race a still-uncommitted write
        """
        node.is_active = False
        node.next_run_date_time = None
        node.save(update_fields=["is_active", "next_run_date_time", "updated_at"])

        from tables.graph_collab.notifications import GraphEditNotifier

        transaction.on_commit(
            lambda: GraphEditNotifier.notify_schedule_node_deactivated(
                node.graph_id, node.id
            )
        )

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

        after_utc = (after or datetime.now(_tz.utc)).astimezone(_tz.utc)
        nxt = trigger.get_next_fire_time(None, after_utc)
        return nxt.astimezone(_tz.utc) if nxt else None
