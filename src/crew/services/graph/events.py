import threading

from services.graph.exceptions import StopSession


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
