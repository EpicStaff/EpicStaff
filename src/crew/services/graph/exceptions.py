class ReturnCodeError(Exception): ...


class KnowledgeSearchError(Exception): ...


class StopSession(Exception):
    def __init__(self, *args, status: str | None = None, reason: str | None = None):
        self.status = status
        # Optional human-readable reason surfaced via Session.status_data
        # (e.g. "token budget exceeded" for the EST-3285 4.2c hard stop).
        # None for the existing manual-stop/timeout paths, so their
        # behavior is unchanged.
        self.reason = reason

        super().__init__(*args)
