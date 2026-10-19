from datetime import datetime, timedelta

from django.db import transaction
from django.db.models import DateTimeField, ExpressionWrapper, F, Q, Value
from django.utils import timezone
from tables.models import GraphSessionMessage, Session, SessionCallback
from utils.logger import logger

TERMINAL_STATUSES = (
    Session.SessionStatus.END,
    Session.SessionStatus.ERROR,
    Session.SessionStatus.STOP,
    Session.SessionStatus.EXPIRED,
)
# How long the reaper waits past a deadline before acting: the manager expiring a
# session (then crew publishing `expired`), or the listener enqueuing a finished one.
STALE_MARGIN = timedelta(minutes=5)
REAP_BATCH_SIZE = 50


class SessionCallbackService:
    """Turn a finished session into a pending callback delivery."""

    @staticmethod
    def end_node_result(session_id: int):
        """Return the persisted `graph_end` result of a session, or None if not stored yet.

        The `graph_end` message is written by the `cache_redis` process, not the one
        that handles statuses, so it can land a moment after the terminal status.
        """
        return (
            GraphSessionMessage.objects.filter(
                session_id=session_id, message_data__message_type="graph_end"
            )
            .order_by("-id")
            .values_list("message_data__end_node_result", flat=True)
            .first()
        )

    def enqueue(self, session_id: int, status: str, token_usage: dict) -> bool:
        """Move a registered callback to `pending` with its payload.

        Idempotent: only a `registered` row moves, so a second terminal status
        (an `expired` after an `end`) changes nothing.

        Returns:
            True when a row was moved to `pending`.
        """
        if status not in TERMINAL_STATUSES:
            return False
        with transaction.atomic():
            callback = (
                SessionCallback.objects.select_for_update()
                .filter(session_id=session_id, status=SessionCallback.Status.REGISTERED)
                .select_related("session")
                .first()
            )
            if callback is None:
                return False
            now = timezone.now()
            callback.payload = {
                "session_id": session_id,
                "graph_id": callback.session.graph_id,
                "status": status,
                "end_node_result": self.end_node_result(session_id),
                "token_usage": token_usage,
                "finished_at": now.isoformat(),
            }
            callback.status = SessionCallback.Status.PENDING
            callback.next_attempt_at = now
            callback.save(update_fields=["payload", "status", "next_attempt_at", "updated_at"])
        logger.info("Session {} callback queued with status {}", session_id, status)
        return True

    def reap_stale(self, now: datetime) -> int:
        """Settle `registered` rows the Redis status listener should have moved by now.

        If crew, the manager or the listener is down, a row would otherwise wait in
        `registered` forever with its secret stored. A row is stale when either:

        - its session is terminal and finished more than `STALE_MARGIN` ago, so the
          listener's enqueue was missed; it is enqueued as the listener would have;
        - its session has `time_to_live > 0` and `status_updated_at + time_to_live +
          STALE_MARGIN` has passed, the same timestamp the manager's timeout reads.
          `status_updated_at` is set only by `Session.save()` (creation and saved
          status changes), not by the listener's queryset update. A session past this
          deadline that is still not terminal is presumed lost: the row is marked
          `failed` and its secret cleared; the receiver must reconcile it itself.

        A session with `time_to_live <= 0` has no deadline anywhere in the system, so
        its row is never given up while the session is not terminal.

        Returns:
            The number of stale rows handled in this pass (at most `REAP_BATCH_SIZE`).
        """
        ttl_deadline = ExpressionWrapper(
            F("session__status_updated_at")
            + F("session__time_to_live") * Value(timedelta(seconds=1))
            + Value(STALE_MARGIN),
            output_field=DateTimeField(),
        )
        finished_long_ago = Q(
            session__status__in=TERMINAL_STATUSES,
            session__finished_at__lt=now - STALE_MARGIN,
        )
        stale = list(
            SessionCallback.objects.filter(status=SessionCallback.Status.REGISTERED)
            .alias(ttl_deadline=ttl_deadline)
            .filter(finished_long_ago | Q(session__time_to_live__gt=0, ttl_deadline__lt=now))
            .select_related("session")
            .order_by("id")[:REAP_BATCH_SIZE]
        )
        for callback in stale:
            session = callback.session
            try:
                if session.status in TERMINAL_STATUSES:
                    self.enqueue(session.pk, session.status, session.token_usage)
                else:
                    self._give_up(callback, session.status, now)
            except Exception as exc:  # one bad row must not stall the rows behind it
                logger.error("Session {} stale callback not settled: {}", session.pk, exc)
        return len(stale)

    @staticmethod
    def _give_up(callback: SessionCallback, session_status: str, now: datetime) -> None:
        # Filtered on `registered`: the status listener may have enqueued it meanwhile.
        moved = SessionCallback.objects.filter(
            pk=callback.pk, status=SessionCallback.Status.REGISTERED
        ).update(
            status=SessionCallback.Status.FAILED,
            encrypted_secret="",
            last_error=f"Session still '{session_status}' past its time_to_live deadline.",
            updated_at=now,
        )
        if moved:
            logger.warning(
                "Session {} callback given up: session stuck in '{}'",
                callback.session_id,
                session_status,
            )
