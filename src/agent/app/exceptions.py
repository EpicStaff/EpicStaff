"""
Domain exception hierarchy for the agent service.

All exceptions raised by service-layer code descend from
``AgentServiceError`` so callers can catch the entire domain at once or
target specific failure modes.  ``RequestHandler`` maps these onto
``emitter.on_error`` and always acks the stream message to avoid poison-pill
re-delivery.
"""

from foundation.schemas import ErrorDetailSchema

from shared.models.agent_service import LoopResult

# What crew shows when a failure has no user-safe fact of its own.
AGENT_FAILED = ErrorDetailSchema(code="agent_failed", detail="The agent failed.")


def loop_error_detail(result: LoopResult) -> ErrorDetailSchema | None:
    """Return the user-safe `{code, detail}` a loop run failed with, or None if it has none."""
    if result.error_code is None or result.error is None:
        return None
    return ErrorDetailSchema(code=result.error_code, detail=result.error)


class AgentServiceError(Exception):
    """Base domain error for the agent service.

    ``error`` is the user-safe ``{code, detail}`` crew shows for this failure. ``None``
    means the message is internal, and the emitter sends the generic "The agent failed."
    """

    def __init__(self, message: str = "", *, error: ErrorDetailSchema | None = None) -> None:
        super().__init__(message)
        self.error = error

    @classmethod
    def from_failed_loop(cls, message: str, result: LoopResult) -> "AgentServiceError":
        """Wrap a failed loop run, passing its user-safe fact on to crew."""
        return cls(message, error=loop_error_detail(result))


class UnknownRunTypeError(AgentServiceError):
    """Raised when RunnerFactory receives a run_type with no registered runner."""


class UnknownToolRefError(AgentServiceError):
    """Raised when AgentResolver finds a tool_ref not present in request.tools pool."""


class UnknownCollectionRefError(AgentServiceError):
    """Raised when AgentResolver finds a collection_ref not present in request.collections pool."""


class UnknownS3RefError(AgentServiceError):
    """Raised when AgentResolver finds an s3_ref id not present in request.s3_files pool."""


class DataLoadError(AgentServiceError):
    """Raised when DataLoader cannot fetch or parse the AgentRequest from Redis K/V."""


class DuplicateToolNameError(AgentServiceError):
    """Raised when ToolRegistryBuilder detects a tool name collision (after sanitisation)."""


class SchemaValidationError(AgentServiceError):
    """Raised when output fails output_schema after all enforcement retries."""


class InvalidOutputSchemaError(AgentServiceError):
    """Raised when a task's output_schema is not a recognizable JSON Schema.

    Covers non-dict values, dicts missing a top-level "type" key (e.g. a bare
    field map saved instead of a full schema), and schemas that fail
    jsonschema meta-validation. Not retried — the schema itself is broken, so
    no amount of LLM retries will fix it.
    """


class FallbackLLMFailedError(AgentServiceError):
    """Raised when the fallback LLM also fails after the primary LLM failed.

    The message names both configs and error classes only, never the provider's
    error text; the fallback's error is chained as ``__cause__``.
    """


class RunCancelled(BaseException):
    """Raised when crew withdrew the run (the user stopped the session).

    A ``BaseException``, like ``asyncio.CancelledError``, so the ``except Exception``
    blocks in the loop and runners cannot turn it into a published result or error.
    """


class McpToolError(AgentServiceError):
    """Raised when an MCP tool call or discovery fails."""
