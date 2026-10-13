class ReturnCodeError(Exception): ...


def timeout_message(effective_timeout_seconds: float | None) -> str:
    """Describe a sandbox run killed for running past its execution timeout.

    The sandbox always reports the limit it applied with a timeout; the wording without a
    limit only guards against a result that lacks it.
    """
    if effective_timeout_seconds is None:
        return "Python code exceeded the execution timeout and was terminated."
    return (
        f"Python code exceeded the execution timeout of {effective_timeout_seconds / 60:g} min "
        "and was terminated."
    )


class PythonCodeTimeoutError(ReturnCodeError):
    """The sandbox killed node code that ran past its execution timeout."""

    def __init__(self, timeout_seconds: float | None):
        self.timeout_seconds = timeout_seconds
        super().__init__(timeout_message(timeout_seconds))


class KnowledgeSearchError(Exception): ...


class KeyValueNodeError(Exception): ...


class StopSession(Exception):  # noqa: N818
    def __init__(self, *args, status: str | None = None, reason: str | None = None):
        self.status = status
        # Optional human-readable reason surfaced via Session.status_data.
        # None for the existing manual-stop/timeout paths, so their
        # behavior is unchanged.
        self.reason = reason

        super().__init__(*args)
