"""Tie a failure the user sees to the log line that explains it.

The user gets a short reference instead of the raw exception text, which can carry
credentials, internal hosts or stack details; the raw text goes to the log under the
same reference, so support can find it from what the user reports.
"""

import uuid

from loguru import logger

__all__ = ["REFERENCE_PATTERN", "log_with_reference", "new_reference"]

REFERENCE_PATTERN = r"[0-9a-f]{12}"


def new_reference() -> str:
    """Return a fresh reference matching ``REFERENCE_PATTERN``."""
    return uuid.uuid4().hex[:12]


def log_with_reference(
    template: str,
    /,
    *args: object,
    exception: BaseException | None = None,
    reference: str | None = None,
    **fields: object,
) -> str:
    """Log a failure at ERROR under a reference and return that reference.

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

    Returns:
        The reference, for the caller to cite in the text the user sees.
    """
    reference = reference or new_reference()
    logger.opt(depth=1, exception=exception).error(
        "(reference: {reference}) " + template, *args, reference=reference, **fields
    )
    return reference
