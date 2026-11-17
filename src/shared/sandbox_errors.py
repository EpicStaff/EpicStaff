"""Errors a producer's sandbox client raises.

Every message these classes set is a fixed fact fit to show a user as the failed
node's stderr. None of them ever includes a request body or the text of an httpx
exception: the request carries the execution's secrets in plaintext. What a plain
`SandboxError` carries is up to the client that raises it.
"""

__all__ = [
    "SANDBOX_SERVER_ERROR_MESSAGE",
    "SandboxError",
    "SandboxExecutionLostError",
    "SandboxOverloadedError",
    "SandboxResultTimeoutError",
    "SandboxUnreachableError",
]

# Shown for every sandbox failure the user can do nothing about and should not see the details of.
SANDBOX_SERVER_ERROR_MESSAGE = "The code couldn't run because of a server error."


class SandboxError(Exception):
    """Base class for every sandbox failure; raised as-is for a refused submission."""


class SandboxOverloadedError(SandboxError):
    """Raised when the sandbox stayed full for the whole queue budget."""

    def __init__(self, queue_timeout: float) -> None:
        self.queue_timeout = queue_timeout
        super().__init__("The server was too busy to run the code in time.")


class SandboxExecutionLostError(SandboxError):
    """Raised when the sandbox no longer knows an execution whose result never arrived.

    It restarted, or the result was not delivered.
    """

    def __init__(self) -> None:
        super().__init__(SANDBOX_SERVER_ERROR_MESSAGE)


class SandboxUnreachableError(SandboxError):
    """Raised when the sandbox cannot be reached within the retry budget."""

    def __init__(self) -> None:
        super().__init__(SANDBOX_SERVER_ERROR_MESSAGE)


class SandboxResultTimeoutError(SandboxError):
    """Raised when no result arrived within the caller's backstop."""

    def __init__(self, backstop: float) -> None:
        self.backstop = backstop
        super().__init__("The code's result didn't arrive in time.")
