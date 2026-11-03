import re
from string import Formatter

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

    @classmethod
    def describes(cls, message: str) -> bool:
        """Whether ``message`` is this error's default text, whatever fills its placeholders.

        Only reliable for a template that quotes every value it inserts, as the UV
        package errors do: a placeholder matches one line of text without a single
        quote, so a longer text cannot pass as one of them. An unquoted placeholder,
        like VenvNotFoundError's id, has no such bound.
        """
        pattern = []
        for literal, field_name, _, _ in Formatter().parse(cls.default_message):
            pattern.append(re.escape(literal))
            if field_name is not None:
                pattern.append(r"[^'\n]+")
        return re.fullmatch("".join(pattern), message) is not None


class VenvNotFoundError(BaseError):
    default_message: str = "Venv(id={venv_id}) not found."


class UVBuildError(BaseError):
    default_message: str = "Couldn't install the libraries. Check the library names and versions."


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
