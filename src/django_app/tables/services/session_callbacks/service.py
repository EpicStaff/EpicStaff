from django.db import transaction
from django.utils import timezone
from tables.models import GraphSessionMessage, Session, SessionCallback
from utils.logger import logger

TERMINAL_STATUSES = (
    Session.SessionStatus.END,
    Session.SessionStatus.ERROR,
    Session.SessionStatus.STOP,
    Session.SessionStatus.EXPIRED,
)


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
