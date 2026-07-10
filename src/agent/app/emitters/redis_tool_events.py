"""
RedisStreamToolEventEmitter: extends ``RedisStreamBatchEmitter`` with live
``agent.tool_call`` / ``agent.tool_result`` envelopes published to
``agent.results`` as they happen, in addition to buffering everything for the
terminal ``agent.result`` payload (unchanged by construction — the parent
implementation still owns buffering).

Live envelopes are best-effort: a publish failure is logged and swallowed so
an auxiliary streaming failure never aborts the run.
"""

from __future__ import annotations

from loguru import logger

from app.emitters.redis_batch import RedisStreamBatchEmitter
from app.llm.client import LLMChunk
from app.usage import TokenUsageAccumulator
from shared.models.agent_service import LoopResult, ToolResult
from shared.redis_streams import RedisStreamClient, StreamEnvelope

LIVE_ARGUMENTS_MAX_CHARS = 2000
LIVE_CONTENT_MAX_CHARS = 2000


def _truncate(text: str, max_chars: int) -> tuple[str, bool]:
    if len(text) <= max_chars:
        return text, False

    return text[:max_chars], True


class RedisStreamToolEventEmitter(RedisStreamBatchEmitter):
    """Publishes live tool-call/tool-result events while still buffering.

    Only ``on_tool_call``, ``on_tool_result``, and ``on_chunk`` are overridden.
    ``on_start``, ``on_warning``, ``on_final``, and ``on_error`` inherit the
    batch behavior unchanged.

    Collaborators:
    - ``self._call_names`` — maps a tool-call id to its tool name so the
      later ``agent.tool_result`` envelope (whose ``ToolResult`` carries no
      name) can still report which tool produced it.
    """

    def __init__(
        self,
        client: RedisStreamClient,
        result_stream: str,
        correlation_id: str,
    ) -> None:
        super().__init__(client, result_stream, correlation_id)
        self._call_names: dict[str, str] = {}
        self._current_task: dict | None = None
        self._usage = TokenUsageAccumulator()

    async def _publish_live(self, event_type: str, payload: dict) -> None:
        envelope = StreamEnvelope(
            type=event_type,
            correlation_id=self._correlation_id,
            payload=payload,
        )

        try:
            await self._client.publish(self._result_stream, envelope.to_fields())
        except Exception as error:
            logger.warning(
                "failed to publish live {} correlation_id={} error={}",
                event_type,
                self._correlation_id,
                error,
            )

    async def on_task_start(self, task_name: str, task_order: int) -> None:
        """Record the currently running task so live tool events can carry it,
        and publish a live ``agent.task_start`` envelope."""
        self._current_task = {"name": task_name, "order": task_order}
        await self._publish_live("agent.task_start", {"task": self._current_task})

    async def on_task_finish(
        self, task_name: str, task_order: int, result: LoopResult
    ) -> None:
        """Publish a live ``agent.task_finish`` envelope carrying the task's
        own result, then clear the current-task label and reset the live
        token-usage delta so it doesn't bleed into the next task."""
        message, truncated = _truncate(result.final_text or "", LIVE_CONTENT_MAX_CHARS)
        await self._publish_live(
            "agent.task_finish",
            {
                "task": {"name": task_name, "order": task_order},
                "message": message,
                "truncated": truncated,
                "token_usage": result.token_usage.model_dump(),
                "iterations": result.iterations,
                "tool_invocations": result.tool_invocations,
                "stop_reason": result.stop_reason,
            },
        )
        self._usage.consume_delta()
        self._current_task = None

    async def on_chunk(self, chunk: LLMChunk) -> None:
        """Accumulate cumulative token usage, then keep buffering as usual."""
        if chunk.usage:
            self._usage.add(chunk.usage)

        await super().on_chunk(chunk)

    async def on_tool_call(self, call: dict) -> None:
        """Publish a live ``agent.tool_call`` envelope, then buffer as usual."""
        call_id = call.get("id")
        name = call.get("name")
        self._call_names[call_id] = name

        arguments, truncated = _truncate(
            call.get("arguments", ""), LIVE_ARGUMENTS_MAX_CHARS
        )
        await self._publish_live(
            "agent.tool_call",
            {
                "id": call_id,
                "name": name,
                "arguments": arguments,
                "truncated": truncated,
                "token_usage": self._usage.consume_delta(),
                "task": self._current_task,
            },
        )

        await super().on_tool_call(call)

    async def on_tool_result(self, result: ToolResult) -> None:
        """Publish a live ``agent.tool_result`` envelope, then buffer as usual."""
        content, truncated = _truncate(result.content, LIVE_CONTENT_MAX_CHARS)
        await self._publish_live(
            "agent.tool_result",
            {
                "tool_call_id": result.tool_call_id,
                "name": self._call_names.get(result.tool_call_id),
                "content": content,
                "is_error": result.is_error,
                "truncated": truncated,
                "token_usage": self._usage.consume_delta(),
                "task": self._current_task,
            },
        )

        await super().on_tool_result(result)
