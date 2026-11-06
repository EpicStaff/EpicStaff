import asyncio
import atexit
import os
import threading

from django.conf import settings
from loguru import logger
from src.shared.audit.client import AuditClient
from src.shared.models import UserActionEvent

_INGEST_PATH = "/api/audit/user_actions/events"


class UserAuditSender:
    """Hands user-action events from Django's sync code to an `AuditClient`.

    The client is async, Django is not: the sender runs the client on its own event loop
    in a daemon thread, started on the first event, so a process that records nothing
    starts nothing. One sender serves one process; `get_user_audit_sender` replaces it in
    a forked child (a gunicorn worker), where the parent's thread does not exist.
    """

    def __init__(self):
        self.pid = os.getpid()
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._client: AuditClient[UserActionEvent] | None = None

    def send(self, events: list[UserActionEvent]) -> None:
        """Queue `events` for the auditor. Never raises; a no-op while the switch is off."""
        if not settings.USER_AUDIT_TRAIL_ENABLED:
            return
        try:
            loop, client = self._started()
            for event in events:
                asyncio.run_coroutine_threadsafe(client.emit(event), loop)
        except Exception:
            logger.exception("Dropping {} user action audit event(s)", len(events))

    def shutdown(self) -> None:
        """Flush what is queued and stop the thread; bounded by `AuditClient.shutdown`."""
        # An atexit hook inherited from the parent process: its thread is not here to join.
        if self.pid != os.getpid():
            return
        with self._lock:
            loop, client = self._loop, self._client
            self._loop, self._client = None, None
        if loop is None:
            return
        try:
            # Above the client's own 5 s drain cap, so only a loop that stopped running trips it.
            asyncio.run_coroutine_threadsafe(client.shutdown(), loop).result(timeout=10)
        except Exception:
            logger.exception("Failed to flush user action audit events on shutdown")
        finally:
            loop.call_soon_threadsafe(loop.stop)

    def _started(self) -> tuple[asyncio.AbstractEventLoop, AuditClient[UserActionEvent]]:
        with self._lock:
            if self._loop is None:
                loop = asyncio.new_event_loop()
                threading.Thread(
                    target=_run_until_stopped, args=(loop,), name="user-audit-sender", daemon=True
                ).start()
                try:
                    # AuditClient starts its flush task on construction, so it is built on the loop.
                    self._client = asyncio.run_coroutine_threadsafe(_create_client(), loop).result()
                except Exception:
                    loop.call_soon_threadsafe(loop.stop)
                    raise
                self._loop = loop
                atexit.register(self.shutdown)
            return self._loop, self._client


def _run_until_stopped(loop: asyncio.AbstractEventLoop) -> None:
    asyncio.set_event_loop(loop)
    loop.run_forever()
    loop.close()


async def _create_client() -> AuditClient[UserActionEvent]:
    return AuditClient(
        base_url=settings.AUDITOR_URL,
        ingest_path=_INGEST_PATH,
        api_key=settings.AUDITOR_INGEST_API_KEY,
    )


_sender_lock = threading.Lock()
_sender: UserAuditSender | None = None


def get_user_audit_sender() -> UserAuditSender:
    """Return this process's sender, creating it on first use and again after a fork."""
    global _sender
    with _sender_lock:
        if _sender is None or _sender.pid != os.getpid():
            _sender = UserAuditSender()
        return _sender
