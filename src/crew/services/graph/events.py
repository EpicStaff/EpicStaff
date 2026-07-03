import threading

from services.graph.exceptions import StopSession


class StopEvent(threading.Event):
    def __init__(self, default_status="stop", *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.status = default_status

    def check_stop(self):
        if self.is_set():
            raise StopSession(status=self.status)
