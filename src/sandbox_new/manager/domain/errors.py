__all__ = [
    "ExecutionNotFoundError",
    "SandboxOverloadedError",
    "UVBuildError",
    "UVDependencyResolutionError",
    "UVPackageNotFoundError",
    "UVVersionNotFoundError",
    "VenvNotFoundError",
]


class BaseError(Exception):
    """Base class for domain errors"""

    default_message: str = ""

    def __init__(self, message: str = "", *args, **format_kwargs) -> None:
        if not message and self.default_message:
            message = self.default_message.format(**format_kwargs)
        super().__init__(message, *args)


class VenvNotFoundError(BaseError):
    default_message: str = "Venv(id={venv_id}) not found."


class UVBuildError(BaseError):
    default_message: str = (
        "Could not build the environment. Check the library names and version specifications."
    )


class UVPackageNotFoundError(BaseError):
    default_message: str = "Package '{package}' does not exist."


class UVVersionNotFoundError(BaseError):
    default_message: str = "Package '{package}' has no version matching '{specification}'."


class UVDependencyResolutionError(BaseError):
    default_message: str = (
        "Package '{package}' requires versions of its dependencies "
        "that conflict with the other requested packages."
    )


class ExecutionNotFoundError(BaseError):
    default_message: str = "Execution(id={execution_id}) not found."

    def __init__(self, execution_id: str) -> None:
        super().__init__(execution_id=execution_id)


class SandboxOverloadedError(BaseError):
    """The sandbox cannot take another execution now.

    Args:
        retry_after: Seconds the caller should wait before re-posting.
    """

    default_message: str = "The sandbox is full; retry later."

    def __init__(self, *, retry_after: int) -> None:
        super().__init__()
        self.retry_after = retry_after
