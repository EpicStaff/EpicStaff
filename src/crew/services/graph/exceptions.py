class ReturnCodeError(Exception): ...


class StopSession(Exception):
    def __init__(self, *args, status: str | None = None, reason: str | None = None):
        self.status = status
        # Optional human-readable reason surfaced via Session.status_data.
        # None for the existing manual-stop/timeout paths, so their
        # behavior is unchanged.
        self.reason = reason

        super().__init__(*args)
