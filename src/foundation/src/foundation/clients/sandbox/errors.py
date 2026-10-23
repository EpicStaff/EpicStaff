"""Errors a producer gets from `SandboxClient`.

Every message is fit to show a user as the failed node's stderr. None of them ever
includes a request body or the text of an httpx exception: the request carries the
execution's secrets in plaintext.
"""

from foundation.transport.http.errors import ClientError

__all__ = [
    "SandboxError",
    "SandboxExecutionLostError",
    "SandboxOverloadedError",
    "SandboxResultTimeoutError",
    "SandboxUnreachableError",
]


class SandboxError(ClientError):
    """Base class for every sandbox failure; raised as-is for a refused submission.

    A refused submission (400, 404 unknown venv, 422, 500 ...) carries the sandbox's
    own error body as its message.
    """


class SandboxOverloadedError(SandboxError):
    """Raised when the sandbox stayed full for the whole queue budget."""

    def __init__(self, queue_timeout: float) -> None:
        super().__init__(f"Sandbox overloaded: no free capacity within {queue_timeout:g} s.")


class SandboxExecutionLostError(SandboxError):
    """Raised when the sandbox no longer knows an execution whose result never arrived."""

    def __init__(self) -> None:
        super().__init__(
            "The sandbox lost the execution (it restarted, or its result was not delivered)."
        )


class SandboxUnreachableError(SandboxError):
    """Raised when the sandbox cannot be reached within the retry budget."""

    def __init__(self) -> None:
        super().__init__("The sandbox is unreachable.")


class SandboxResultTimeoutError(SandboxError):
    """Raised when no result arrived within the caller's backstop."""

    def __init__(self, backstop: float) -> None:
        super().__init__(f"Timed out waiting for the result after {backstop:g} s.")
