"""Why a code execution failed, in a form a consumer can branch on.

A failed code result carries one `CodeFailure` next to its stderr. `detail` is the
sentence the user sees, the same line the sandbox appends to stderr, so a consumer that
only reads stderr shows the same text. The JSON shape is a superset of foundation's
`ErrorDetailSchema` (`code`, `detail`, `attr`), with one optional nested object.
"""

from enum import StrEnum

from pydantic import BaseModel, model_validator

__all__ = [
    "SERVER_FAILURE_CODES",
    "USER_CODE_LOCATION_TEMPLATE",
    "WRAPPER_FAILURE_CODES",
    "CodeFailure",
    "CodeFailureCode",
    "UserCodeError",
    "describe_user_code_error",
]


class CodeFailureCode(StrEnum):
    """What went wrong; the comment on each names the part of the system that reports it.

    Read leniently: a code this version doesn't know is read as ``UNKNOWN`` rather than
    rejected, because a newer producer can send one during a deploy. A consumer shows
    the failure's ``detail`` for it, which is always safe to show.
    """

    # The sandbox's code wrapper, from inside the process that ran the user's code.
    USER_CODE_ERROR = "user_code_error"
    MISSING_ENTRYPOINT = "missing_entrypoint"
    UNEXPECTED_ARGUMENT = "unexpected_argument"
    MISSING_ARGUMENT = "missing_argument"
    BAD_RETURN_VALUE = "bad_return_value"
    NETWORK_DENIED = "network_denied"
    # The sandbox worker, around the process.
    CODE_EXITED = "code_exited"
    EXECUTION_TIMEOUT = "execution_timeout"
    RESULT_TOO_LARGE = "result_too_large"
    SANDBOX_ERROR = "sandbox_error"
    UNSAFE_TO_RUN = "unsafe_to_run"
    OVERLOADED = "overloaded"
    # The sandbox manager, for a job that never reached the worker. The package codes
    # are the venv build error kinds.
    PACKAGE_NOT_FOUND = "package_not_found"
    PACKAGE_VERSION_NOT_FOUND = "package_version_not_found"
    PACKAGE_DEPENDENCY_CONFLICT = "package_dependency_conflict"
    PACKAGE_INSTALL_FAILED = "package_install_failed"
    HOLD_TIMEOUT = "hold_timeout"
    DISPATCH_FAILED = "dispatch_failed"
    # Crew, when it stopped waiting for the result.
    RESULT_TIMEOUT = "result_timeout"
    # Never sent: what a consumer reads a code it doesn't know as.
    UNKNOWN = "unknown"

    @classmethod
    def _missing_(cls, value: object) -> "CodeFailureCode | None":
        # Only a value a newer producer could send; anything but a string is malformed.
        return cls.UNKNOWN if isinstance(value, str) else None


# The codes the process running the user's code may report about itself. That process
# also runs the user's code, so the worker trusts no other code from it: a claim of a
# server failure there would let the user's code pass itself off as the sandbox.
WRAPPER_FAILURE_CODES = frozenset(
    {
        CodeFailureCode.USER_CODE_ERROR,
        CodeFailureCode.MISSING_ENTRYPOINT,
        CodeFailureCode.UNEXPECTED_ARGUMENT,
        CodeFailureCode.MISSING_ARGUMENT,
        CodeFailureCode.BAD_RETURN_VALUE,
        CodeFailureCode.NETWORK_DENIED,
    }
)

# The failures only a server log line explains: the failure cites the reference that line
# is logged under, and a consumer names its own context around it rather than showing the
# detail alone.
SERVER_FAILURE_CODES = frozenset(
    {
        CodeFailureCode.SANDBOX_ERROR,
        CodeFailureCode.DISPATCH_FAILED,
        CodeFailureCode.UNSAFE_TO_RUN,
    }
)

_ARGUMENT_CODES = frozenset({CodeFailureCode.UNEXPECTED_ARGUMENT, CodeFailureCode.MISSING_ARGUMENT})

# The sandbox's code wrapper can't import this module, so it embeds the template as a
# literal; `describe_user_code_error` is the same formatting for everyone else.
USER_CODE_LOCATION_TEMPLATE = "{exception_type} on line {line}"


def describe_user_code_error(exception_type: str, line: int | None, message: str) -> str:
    """Return the line a user sees for an error in their code: "<Type> on line <N>: <message>".

    The line number is left out when the error has none in the user's code, and the
    message when it is empty.
    """
    location = (
        exception_type
        if line is None
        else USER_CODE_LOCATION_TEMPLATE.format(exception_type=exception_type, line=line)
    )
    return f"{location}: {message}" if message else location


class UserCodeError(BaseModel):
    """The exception the user's code raised, in parts.

    `line` is the user's own line: where a syntax error is, or the deepest frame of their
    code the exception passed through. None when the exception never passed through it.
    """

    exception_type: str
    line: int | None = None
    message: str


class CodeFailure(BaseModel):
    """Why a code execution failed.

    Attributes:
        detail: The sentence the user sees; always safe to show. On a sandbox result it is
            the line appended to stderr.
        attr: The argument at fault, for `unexpected_argument` and `missing_argument`.
        user_error: The exception in parts, for `user_code_error`.
    """

    code: CodeFailureCode
    detail: str
    attr: str | None = None
    user_error: UserCodeError | None = None

    @model_validator(mode="after")
    def _keep_only_the_parts_of_the_code(self) -> "CodeFailure":
        # The parts a consumer reads for the code are required. A part on another code is
        # dropped rather than rejected, so a newer producer's failure is still read, and
        # every consumer can trust a part to mean its code.
        if self.code in _ARGUMENT_CODES and self.attr is None:
            raise ValueError("an argument code needs attr")
        if self.code is CodeFailureCode.USER_CODE_ERROR and self.user_error is None:
            raise ValueError("user_code_error needs user_error")
        if self.code not in _ARGUMENT_CODES:
            self.attr = None
        if self.code is not CodeFailureCode.USER_CODE_ERROR:
            self.user_error = None
        return self
