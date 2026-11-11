class ReturnCodeError(Exception): ...


class KnowledgeSearchError(Exception): ...


class KeyValueNodeError(Exception): ...


class InvalidStatePathError(Exception):
    """A flow state path the flow author wrote cannot be read or written.

    The message names only the author's own path, so it is safe to show to the user.
    """


class StopSession(Exception):  # noqa: N818
    def __init__(self, *args, status: str | None = None, reason: str | None = None):
        self.status = status
        # Optional human-readable reason surfaced via Session.status_data.
        # None for the existing manual-stop/timeout paths, so their
        # behavior is unchanged.
        self.reason = reason

        super().__init__(*args)
