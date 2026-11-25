import uuid
from enum import StrEnum


class PublicErrorMessage(StrEnum):
    """Fixed texts that may leave the service in place of raw exception text."""

    MESSAGE_PROCESSING_FAILED = "Failed to process the message"
    TOOL_EXECUTION_FAILED = "Tool execution failed"
    KNOWLEDGE_SEARCH_FAILED = "Knowledge search failed"
    # The knowledge-search failures that searching again cannot fix say so, or a model
    # reading the tool result keeps retrying them.
    KNOWLEDGE_BASE_NOT_FOUND = (
        "Knowledge search failed: the knowledge base was not found. Retrying will not help"
    )
    KNOWLEDGE_BASE_NOT_INDEXED = (
        "Knowledge search failed: the knowledge base has not been indexed yet. "
        "Retrying will not help until it is indexed"
    )
    KNOWLEDGE_SEARCH_REJECTED = (
        "Knowledge search failed: the knowledge service rejected the request. "
        "Retrying will not help"
    )
    NODE_EXECUTION_FAILED = "Node execution failed"
    SESSION_EXECUTION_FAILED = "Session execution failed"


def new_error_correlation_id() -> str:
    """Return a short id that ties an outbound error message to its log line."""
    return uuid.uuid4().hex[:12]


def build_public_error_message(message: PublicErrorMessage, correlation_id: str) -> str:
    """Build the text sent to a client or provider when an operation fails.

    Raw exception text can carry credentials, internal hosts or stack details, so
    it stays in the logs; the caller logs it with the same correlation id.
    """
    return f"{message} (reference: {correlation_id})"
