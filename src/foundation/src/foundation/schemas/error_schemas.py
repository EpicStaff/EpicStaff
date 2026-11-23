"""Response schemas for the one shape every service answers an error with.

Only the shape lives here, never the exceptions that lead to it -- those stay with the
code that raises them. Kept out of the framework helpers too, so a Django service
imports it as readily as a Litestar one: nothing here knows how a response is sent.
"""

from enum import StrEnum
from typing import Any, Self

from pydantic import Field

from .base import Schema

__all__ = [
    "INTERNAL_ERROR_DETAIL",
    "UNKNOWN_ERROR_CODE",
    "ErrorDetailSchema",
    "ErrorResponseSchema",
    "ErrorType",
]

# What a caller reads for an error nobody handled; the error itself goes to the log only.
INTERNAL_ERROR_DETAIL = "Internal server error."

# The code that error carries: nothing more specific is known about it.
UNKNOWN_ERROR_CODE = "unknown"


class ErrorType(StrEnum):
    """Whose fault the error is: the caller's, or the service's."""

    CLIENT_ERROR = "client_error"
    SERVER_ERROR = "server_error"


class ErrorDetailSchema(Schema):
    """One thing that went wrong.

    Serialised with every key, `attr` and `context` included as null when absent, so a
    client reads the same four keys from every item.
    """

    code: str = Field(description="Machine-readable name for what went wrong.")
    detail: str = Field(description="What went wrong, in words.")
    attr: str | None = Field(
        default=None,
        description=(
            "The request field at fault, dotted for a nested one. Null when the error "
            "belongs to no single field."
        ),
    )
    context: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Structured facts about the error, safe to show any API client: ids, names, "
            "versions, limits. Never secrets, request bodies, raw upstream text or operator "
            "hints such as environment variables, kernel versions or filesystem paths."
        ),
    )


class ErrorResponseSchema(Schema):
    """The shape every error answer takes, whatever the status code.

    A 400, a 404 and a 500 differ only in ``type`` and in what ``errors`` holds, so a
    client parses one shape instead of a different one per endpoint. ``errors`` is a
    list because one request can be wrong in several places at once.
    """

    type: ErrorType
    errors: list[ErrorDetailSchema]

    @classmethod
    def for_status(cls, status_code: int, errors: list[ErrorDetailSchema]) -> Self:
        """Build the envelope an answer with ``status_code`` carries.

        ``type`` is derived rather than passed in so it cannot drift from the status
        code: anything below 500 is the caller's error, anything from 500 up is ours.
        """
        return cls(
            type=ErrorType.CLIENT_ERROR if status_code < 500 else ErrorType.SERVER_ERROR,
            errors=errors,
        )
