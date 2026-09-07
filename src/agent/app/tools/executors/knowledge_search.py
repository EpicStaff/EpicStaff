from __future__ import annotations

from loguru import logger

from shared.models.agent_service import ToolResult

from app.knowledge.client import KnowledgeClient
from app.knowledge.events import KnowledgeEventSink
from app.knowledge.target import KnowledgeSearchTarget
import settings

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
        resp = await client.search(target, query, timeout=timeout)

    except Exception as error:
        return ToolResult(
            tool_call_id="",
            content=f"Knowledge search failed: {error}",
            is_error=True,
        )

    if sink is not None:
        try:
            await sink.on_knowledge_search(resp)

        except Exception as sink_error:
            logger.warning(
                "knowledge search sink failed rag_id={} error={}",
                target.rag_id,
                sink_error,
            )

    if not resp.chunks:
        return ToolResult(
            tool_call_id="",
            content="No relevant results found.",
            is_error=False,
        )

    lines = [
        f"{chunk.chunk_text} (source={chunk.chunk_source}, score={chunk.chunk_similarity})"
        for chunk in resp.chunks
    ]
    return ToolResult(
        tool_call_id="",
        content="\n\n".join(lines),
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
