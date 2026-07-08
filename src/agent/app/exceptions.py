"""
Domain exception hierarchy for the agent service.

All exceptions raised by service-layer code descend from
``AgentServiceError`` so callers can catch the entire domain at once or
target specific failure modes.  ``RequestHandler`` maps these onto
``emitter.on_error`` and always acks the stream message to avoid poison-pill
re-delivery.
"""


class AgentServiceError(Exception):
    """Base domain error for the agent service."""


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


class McpToolError(AgentServiceError):
    """Raised when an MCP tool call or discovery fails."""
