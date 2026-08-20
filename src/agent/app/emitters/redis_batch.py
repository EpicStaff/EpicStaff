"""
RedisStreamBatchEmitter: buffers all mid-execution events and publishes a
single ``agent.result`` (or ``agent.error``) envelope to the ``agent.results``
Redis Stream only on ``on_final`` / ``on_error``.

This is the only ``Emitter`` implementation built in this plan; it is used
by all runners that declare ``emitter_mode = EmitterMode.BATCH``.
"""

from __future__ import annotations

from loguru import logger

from app.emitters.base import Emitter
from app.llm.client import LLMChunk
from app.logging_utils import redact
from shared.models.agent_service import AgentRequest, LoopResult, ToolResult
from shared.redis_streams import RedisStreamClient, StreamEnvelope


class RedisStreamBatchEmitter(Emitter):
    """Buffers events and publishes one result envelope per ``AgentLoop`` run.

    Collaborators:
    - ``RedisStreamClient`` — used to publish the final envelope via
      ``client.publish(result_stream, envelope.to_fields())``.
    - ``StreamEnvelope`` — wraps the payload with type and correlation_id.

    Invariant: ``on_final`` and ``on_error`` each publish exactly one
    message to ``result_stream``; they must not both be called for the same
    run.
    """

    def __init__(
        self,
        client: RedisStreamClient,
        result_stream: str,
        correlation_id: str,
    ) -> None:
        self._client = client
        self._result_stream = result_stream
        self._correlation_id = correlation_id
        self._buffered_events: list[dict] = []
        self._warnings: list[str] = []

    async def on_start(self, request: AgentRequest) -> None:
        """Log the start of a run; no event is buffered or published yet."""
        logger.debug("emitter on_start correlation_id={}", self._correlation_id)

    async def on_chunk(self, chunk: LLMChunk) -> None:
        """Buffer an LLM chunk event for inclusion in the final envelope."""
        self._buffered_events.append({"event": "chunk", "data": chunk.model_dump()})

    async def on_tool_call(self, call: object) -> None:
        """Buffer a tool-call event for inclusion in the final envelope."""
        self._buffered_events.append({"event": "tool_call", "data": str(call)})

    async def on_tool_result(self, result: ToolResult) -> None:
        """Buffer a tool-result event for inclusion in the final envelope."""
        self._buffered_events.append(
            {"event": "tool_result", "data": result.model_dump()}
        )

    async def on_warning(self, message: str) -> None:
        """Buffer an advisory warning; deduplicate identical messages."""
        if message not in self._warnings:
            self._warnings.append(message)
        logger.debug(
            "emitter on_warning correlation_id={} message={}",
            self._correlation_id,
            message,
        )

    async def on_final(self, result: LoopResult) -> None:
        """Publish a single ``agent.result`` envelope containing the loop summary and all buffered events."""
        envelope = StreamEnvelope(
            type="agent.result",
            correlation_id=self._correlation_id,
            payload={
                "final_text": result.final_text,
                "tool_invocations": result.tool_invocations,
                "iterations": result.iterations,
                "stop_reason": result.stop_reason,
                "token_usage": result.token_usage.model_dump(),
                "error": result.error,
                "events": self._buffered_events,
                "warnings": self._warnings,
                "tasks": (
                    [task.model_dump() for task in result.tasks]
                    if result.tasks is not None
                    else None
                ),
            },
        )
        _corr_id = self._correlation_id
        logger.opt(lazy=True).debug(
            "agent.result correlation_id={} payload={}",
            lambda: _corr_id,
            lambda: redact(envelope.payload),
        )
        await self._client.publish(self._result_stream, envelope.to_fields())
        logger.info("published agent.result correlation_id={}", self._correlation_id)

    async def on_error(self, error: Exception) -> None:
        """Publish a single ``agent.error`` envelope carrying the error message."""
        envelope = StreamEnvelope(
            type="agent.error",
            correlation_id=self._correlation_id,
            payload={"error": str(error), "warnings": self._warnings},
        )
        await self._client.publish(self._result_stream, envelope.to_fields())
        logger.error(
            "published agent.error correlation_id={} error={}",
            self._correlation_id,
            error,
        )
