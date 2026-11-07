"""Tie a failure the user sees to the log line that explains it.

The user gets a short reference instead of the raw exception text, which can carry
credentials, internal hosts or stack details; the raw text goes to the log under the
same reference, so support can find it from what the user reports.

Also holds the generic server-failure text and error code, so every service answers an
unexplained failure with the same words.
"""

import re
import uuid

from loguru import logger

__all__ = [
    "INTERNAL_ERROR_CODE",
    "INTERNAL_ERROR_MESSAGE",
    "REFERENCE_PATTERN",
    "SERVER_FAILURE_TEXT",
    "log_with_reference",
    "new_reference",
    "trusted_reference",
]

REFERENCE_PATTERN = r"[0-9a-f]{12}"

# The error code of a response to a failure nothing more specific explains.
INTERNAL_ERROR_CODE = "internal_error"
# Without a closing period, so a message can end it with or without a reference.
SERVER_FAILURE_TEXT = "Something went wrong on the server. Try again or contact your administrator"
INTERNAL_ERROR_MESSAGE = f"{SERVER_FAILURE_TEXT} (reference: {{reference}})."

_REFERENCE = re.compile(REFERENCE_PATTERN)


def new_reference() -> str:
    """Return a fresh reference matching ``REFERENCE_PATTERN``."""
    return uuid.uuid4().hex[:12]


def trusted_reference(value: object) -> str | None:
    """Return ``value`` if it is a well-formed reference, else None.

    For a reference that arrives from another service: it ends up in the text the user
    sees, so anything that doesn't match ``REFERENCE_PATTERN`` exactly is dropped.
    """
    if isinstance(value, str) and _REFERENCE.fullmatch(value):
        return value
    return None


def log_with_reference(
    template: str,
    /,
    *args: object,
    exception: BaseException | None = None,
    reference: str | None = None,
    level: str = "ERROR",
    **fields: object,
) -> str:
    """Log a failure under a reference and return that reference.

    The reference opens the message because some sinks cut long messages short (the
    Django one keeps the first 200 characters), and it is also bound as the record's
    ``reference`` extra. The record names the caller, not this function.

    Raw text -- exception messages, provider responses, user input -- goes in ``args``
    or ``fields``, never into ``template``: the template is formatted with
    ``str.format``, so a brace in raw text would break the message or raise.

    Args:
        template: Loguru message with ``{}`` or ``{name}`` placeholders for ``args``
            and ``fields``.
        exception: Logged with its traceback when given.
        reference: Reuse a reference minted earlier, for a caller that has to know it
            before the failure happens. A new one is minted when omitted.
        level: Loguru level name. ERROR by default; WARNING for an expected failure
            that shouldn't raise an alert, such as a run hitting its own time limit.

    Returns:
        The reference, for the caller to cite in the text the user sees.
    """
    reference = reference or new_reference()
    logger.opt(depth=1, exception=exception).log(
        level, "(reference: {reference}) " + template, *args, reference=reference, **fields
    )
    return reference
