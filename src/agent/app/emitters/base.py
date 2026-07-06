"""
Emitter ABC: transport-agnostic output sink (Bridge pattern).

The Emitter is the Bridge between the agent execution layers (Runner,
AgentLoop) and the output transport (Redis Streams, WebSocket, etc.).
Concrete implementations differ in *when* they publish and *what* they
include.  ``RunnerFactory`` selects the implementation; neither Runner nor
AgentLoop knows which one is active.

Hooks mirror the lifecycle of a single ``AgentLoop`` execution:
``on_start`` → (``on_chunk`` / ``on_tool_call`` / ``on_tool_result`` /
``on_warning``) * N → ``on_final`` | ``on_error``.
``on_warning`` may fire at any point between ``on_start`` and
``on_final`` / ``on_error``; it is advisory and must never raise.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.llm.client import LLMChunk
from shared.models.agent_service import AgentRequest, LoopResult, ToolResult


class Emitter(ABC):
    """Abstract output transport for agent execution events.

    Subclasses must implement all six lifecycle hooks.  Implementations may
    buffer events internally (``RedisStreamBatchEmitter``), buffer while also
    publishing select events live (``RedisStreamToolEventEmitter``), or
    publish each event immediately (future ``RedisStreamDeltaEmitter``).

    ``RequestHandler`` holds a reference to the emitter and also constructs
    a fallback ``RedisStreamBatchEmitter`` directly when the factory itself
    fails, so ``on_error`` must be safe to call before ``on_start``.
    """

    @abstractmethod
    async def on_start(self, request: AgentRequest) -> None:
        """Called once before the runner begins execution."""
        ...

    @abstractmethod
    async def on_chunk(self, chunk: LLMChunk) -> None:
        """Called for each ``LLMChunk`` produced by ``LLMClient.chat``."""
        ...

    @abstractmethod
    async def on_tool_call(self, call: object) -> None:
        """Called when the loop dispatches a tool call to ``ToolRegistry``."""
        ...

    @abstractmethod
    async def on_tool_result(self, result: ToolResult) -> None:
        """Called after ``ToolRegistry.execute`` returns a ``ToolResult``."""
        ...

    @abstractmethod
    async def on_final(self, result: LoopResult) -> None:
        """Called once when the loop finishes successfully."""
        ...

    @abstractmethod
    async def on_warning(self, message: str) -> None:
        """Record an advisory, non-fatal warning to include in the response.

        Safe to call any time between on_start and on_final/on_error; must not raise.
        """
        ...

    @abstractmethod
    async def on_error(self, error: Exception) -> None:
        """Called when an unrecoverable error occurs at any pipeline stage.

        Must publish an ``agent.error`` envelope so downstream consumers
        are not left waiting.  Must not raise.
        """
        ...
