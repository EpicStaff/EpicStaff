from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncIterator


class UnsupportedLLMProviderError(Exception):
    """Raised when no client implementation exists for the given provider name."""

    def __init__(self, provider_name: str) -> None:
        self.provider_name = provider_name
        super().__init__(f"Unsupported LLM provider: '{provider_name}'")


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
