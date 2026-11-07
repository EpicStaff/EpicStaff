"""Fixed texts that leave a service in place of raw exception text.

Mint the reference and log the raw error with ``foundation.utils.error_reference``
(``log_with_reference``); the text built here cites that reference.
"""

from enum import StrEnum


class PublicErrorMessage(StrEnum):
    """Fixed texts that may leave the service in place of raw exception text."""

    MESSAGE_PROCESSING_FAILED = "Failed to process the message"
    TOOL_EXECUTION_FAILED = "Tool execution failed"
    KNOWLEDGE_SEARCH_FAILED = "Knowledge search failed"
    NODE_EXECUTION_FAILED = "Node execution failed"


def build_public_error_message(message: PublicErrorMessage, reference: str) -> str:
    """Build the text sent to a client or provider when an operation fails.

    Raw exception text can carry credentials, internal hosts or stack details, so
    it stays in the logs; the caller logs it under the same reference.
    """
    return f"{message} (reference: {reference})"
