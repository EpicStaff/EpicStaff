import asyncio
import threading
from collections.abc import Awaitable

from services.graph.exceptions import StopSession

# StopEvent is a threading.Event and cannot be awaited, so `until_stopped` wakes up this
# often to check it.
STOP_CHECK_INTERVAL_S = 0.5


class StopEvent(threading.Event):
    def __init__(self, default_status="stop", *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.status = default_status
        # Optional reason surfaced when the event is set (e.g. by the
        # token-budget hard stop). None for manual stop /
        # timeout, which keep their current (reason-less) behavior.
        self.reason: str | None = None

    def check_stop(self):
        if self.is_set():
            raise StopSession(status=self.status, reason=self.reason)


async def until_stopped[T](awaitable: Awaitable[T], stop_event: StopEvent | None) -> T:
    """Await `awaitable`, checking `stop_event` every STOP_CHECK_INTERVAL_S.

    Raises:
        StopSession: `stop_event` was set first; `awaitable` is cancelled.
    """
    task = asyncio.ensure_future(awaitable)
    try:
        while not task.done():
            if stop_event is not None:
                stop_event.check_stop()
            await asyncio.wait({task}, timeout=STOP_CHECK_INTERVAL_S)
        return task.result()
    finally:
        task.cancel()
