"""Refusals of the application's own services, as opposed to failures of a port."""

from manager.domain.errors import BaseError, NotFoundError

__all__ = ["ExecutionNotFoundError", "SandboxOverloadedError", "VenvNotFoundError"]


class VenvNotFoundError(NotFoundError):
    """No venv is stored under the id the caller asked for, or there is no default venv."""

    code = "venv_not_found"
    default_message: str = "Venv(id={venv_id}) not found."


class ExecutionNotFoundError(BaseError):
    """The execution registry does not know the execution id."""

    code = "execution_not_found"
    default_message: str = "Execution(id={execution_id}) not found."

    def __init__(self, execution_id: str) -> None:
        super().__init__(execution_id=execution_id)


class SandboxOverloadedError(BaseError):
    """The intake gate refuses another execution now.

    Args:
        retry_after: Seconds the caller should wait before re-posting.
    """

    code = "sandbox_overloaded"
    default_message: str = "The sandbox is full; retry later."

    def __init__(self, *, retry_after: int) -> None:
        super().__init__()
        self.retry_after = retry_after
