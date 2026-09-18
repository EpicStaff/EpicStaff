from __future__ import annotations

import json

from loguru import logger

from shared.models.agent_service import ToolResult
from shared.models.knowledge_new import FoundChunk

from app.knowledge.events import KnowledgeEventSink
from shared.knowledge.target import KnowledgeSearchTarget
from shared.knowledge.client import KnowledgeClient
import settings


async def _notify_sink(
    sink: KnowledgeEventSink | None,
    target: KnowledgeSearchTarget,
    query: str,
    result: list[FoundChunk] | str,
    error: str | None = None,
) -> None:
    """Best-effort notification: a sink failure is logged and swallowed so it
    never affects the tool's own result."""
    if sink is None:
        return

    try:
        await sink.on_knowledge_search(target, query, result, error=error)

    except Exception as sink_error:
        logger.warning(
            "knowledge search sink failed rag_id={} error={}",
            target.rag_id,
            sink_error,
        )


async def _execute_search(
    client: KnowledgeClient,
    target: KnowledgeSearchTarget,
    query: str,
    sink: KnowledgeEventSink | None = None,
) -> ToolResult:
    timeout = (
        settings.GRAPH_RAG_SEARCH_TIMEOUT
        if target.rag_type == "graph"
        else settings.NAIVE_RAG_SEARCH_TIMEOUT
    )

    try:
        result = await client.search(target, query, timeout=timeout)

    except Exception as error:
        await _notify_sink(sink, target, query, [], error=str(error))
        return ToolResult(
            tool_call_id="",
            content=f"Knowledge search failed: {error}",
            is_error=True,
        )

    await _notify_sink(sink, target, query, result)

    if isinstance(result, str):
        return ToolResult(
            tool_call_id="",
            content=result.strip() or "No relevant results found.",
            is_error=False,
        )

    if not result:
        return ToolResult(
            tool_call_id="",
            content="No relevant results found.",
            is_error=False,
        )

    content = json.dumps(
        [
            {"text": chunk.text, "source": chunk.source, "score": chunk.similarity}
            for chunk in result
        ],
        ensure_ascii=False,
    )
    return ToolResult(
        tool_call_id="",
        content=content,
        is_error=False,
    )


class KnowledgeSearchExecutor:
    """Executes a single-target knowledge search (naive or single graph method)."""

    def __init__(
        self,
        client: KnowledgeClient,
        target: KnowledgeSearchTarget,
        sink: KnowledgeEventSink | None = None,
    ) -> None:
        self._client = client
        self._target = target
        self._sink = sink

    async def __call__(self, args: dict) -> ToolResult:
        query = args.get("query")

        if not query:
            return ToolResult(
                tool_call_id="",
                content="knowledge search requires a 'query'",
                is_error=True,
            )

        return await _execute_search(self._client, self._target, query, self._sink)


class GraphKnowledgeSearchExecutor:
    """Executes a graph knowledge search with method dispatch (basic / local).

    Accepts ``search_method`` from tool args.  Unknown or missing method falls
    back to the default (first registered target, typically "basic").
    """

    def __init__(
        self,
        client: KnowledgeClient,
        targets: dict[str, KnowledgeSearchTarget],
        default_method: str,
        sink: KnowledgeEventSink | None = None,
    ) -> None:
        self._client = client
        self._targets = targets
        self._default_method = default_method
        self._sink = sink

    async def __call__(self, args: dict) -> ToolResult:
        query = args.get("query")

        if not query:
            return ToolResult(
                tool_call_id="",
                content="knowledge search requires a 'query'",
                is_error=True,
            )

        method = args.get("search_method") or self._default_method
        target = self._targets.get(method) or self._targets[self._default_method]

        return await _execute_search(self._client, target, query, self._sink)
