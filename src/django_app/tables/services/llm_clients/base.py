from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field


class UnsupportedLLMProviderError(Exception):
    """Raised when no client implementation exists for the given provider name."""

    def __init__(self, provider_name: str) -> None:
        self.provider_name = provider_name
        super().__init__(f"Unsupported LLM provider: '{provider_name}'")


# Provider error code for a reply the provider aborted because the model called a
# tool that was not in the request; the same request usually succeeds on a second try.
TOOL_USE_FAILED_CODE = "tool_use_failed"

# Provider error codes whose message is safe to show any user of the config. Other
# messages (bad key, unknown model or deployment) can echo key fragments or endpoints
# to members who may not see the config itself.
USER_VISIBLE_PROVIDER_ERROR_CODES = frozenset(
    {TOOL_USE_FAILED_CODE, "rate_limit_exceeded", "context_length_exceeded"}
)


class LLMProviderError(Exception):
    """Raised when the LLM provider rejects or aborts a request with an error of its own.

    ``message`` is the provider's own text and ``code`` its error code, when it sent one.
    """

    def __init__(self, provider: str, code: str | None, message: str) -> None:
        self.provider = provider
        self.code = code
        self.message = message
        super().__init__(f"{provider} error ({code}): {message}")


class InvalidLLMConfigError(Exception):
    """Raised when a stored LLM config holds a value no client can send.

    Saving through the API rejects these shapes; this covers rows written before
    that validation existed.
    """

    def __init__(self, llm_config_id: int, field_names: list[str]) -> None:
        self.llm_config_id = llm_config_id
        self.field_names = field_names
        super().__init__(
            f"LLM config {llm_config_id} has an invalid value in: {', '.join(field_names)}. "
            "Edit the config to fix it."
        )


@dataclass
class ToolSpec:
    """Provider-agnostic tool declaration."""

    name: str
    description: str
    parameters: dict  # JSON Schema object


@dataclass
class TokenEvent:
    content: str
    type: str = field(default="token", init=False)


@dataclass
class ToolCallEvent:
    id: str
    name: str
    args: dict
    type: str = field(default="tool_call", init=False)


@dataclass
class ToolResultEvent:
    id: str
    name: str
    content: str
    type: str = field(default="tool_result", init=False)


@dataclass
class DoneEvent:
    interrupted: bool = False
    reasoning_observed: bool = False
    # Provider finish reason of the turn (e.g. "stop", "length"); None when unknown.
    finish_reason: str | None = None
    type: str = field(default="done", init=False)


@dataclass
class StructuredEvent:
    """Emitted once at end-of-stream when the LLM response was structured JSON.

    ``message`` is the canonical plain-text (or markdown) reply.
    ``ef_tables`` and ``action_message`` carry the rich-UI payloads; both
    default to empty lists when the model omitted them.
    """

    message: str
    ef_tables: list = field(default_factory=list)
    action_message: list = field(default_factory=list)
    type: str = field(default="structured", init=False)


StreamEvent = TokenEvent | ToolCallEvent | ToolResultEvent | StructuredEvent | DoneEvent


class BaseLLMClient(ABC):
    """Abstract base for streaming LLM clients that support tool calling."""

    def __init__(self, output_schema: dict | None = None) -> None:
        """Store the optional JSON Schema for structured output.

        Subclasses must call ``super().__init__(output_schema=output_schema)``
        or set ``self._output_schema`` themselves.
        """
        self._output_schema: dict | None = output_schema

    @abstractmethod
    async def stream_completion(
        self,
        messages: list[dict],
        tools: list[ToolSpec],
    ) -> AsyncIterator[StreamEvent]:
        """Stream a completion turn.

        Yields StreamEvent items in order:
        - TokenEvent for each streaming text chunk
        - ToolCallEvent when the model invokes a tool
        - DoneEvent once the turn is complete (text or tool calls)
        """
