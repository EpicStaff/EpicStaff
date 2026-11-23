from __future__ import annotations

import json

import httpx
import settings
from loguru import logger

from app.knowledge.events import KnowledgeEventSink
from app.logging_utils import describe_http_status_error, format_exception_for_log
from shared.knowledge.client import KnowledgeClient
from shared.knowledge.target import KnowledgeSearchTarget
from shared.models.agent_service import ToolResult
from shared.models.knowledge_new import FoundChunk, SearchUsage
from shared.public_error import (
    PublicErrorMessage,
    build_public_error_message,
    new_error_correlation_id,
)


async def _notify_sink(
    sink: KnowledgeEventSink | None,
    target: KnowledgeSearchTarget,
    query: str,
    result: list[FoundChunk] | str,
    error: str | None = None,
    usage: SearchUsage | None = None,
) -> None:
    """Best-effort notification: a sink failure is logged and swallowed so it
    never affects the tool's own result."""
    if sink is None:
        return

    try:
        await sink.on_knowledge_search(target, query, result, error=error, usage=usage)

    except Exception as exc:
        logger.warning(
            "knowledge search sink failed rag_id={} error={}",
            target.rag_id,
            format_exception_for_log(exc),
        )


def _describe_search_failure(error: Exception) -> str:
    # A status error is named by its status and the service's origin; any other
    # exception by its class and a digest, since its message can quote the request.
    if isinstance(error, httpx.HTTPStatusError):
        return describe_http_status_error(error)
    return format_exception_for_log(error)


# The knowledge service's error `code`s for a search that can never succeed as asked.
# Only the code is read: the body's `detail` quotes the service's internals.
# An unmapped code is reported as permanent, so a new code that clears with time needs handling.
_REJECTION_MESSAGES_BY_CODE = {
    "not_found": PublicErrorMessage.KNOWLEDGE_BASE_NOT_FOUND,
    "graph_not_indexed": PublicErrorMessage.KNOWLEDGE_BASE_NOT_INDEXED,
}

# Client errors that do pass with time, so they are not reported as permanent.
_TRANSIENT_CLIENT_ERROR_STATUSES = frozenset({408, 429})


def _client_error_message(response: httpx.Response) -> PublicErrorMessage:
    if response.status_code in _TRANSIENT_CLIENT_ERROR_STATUSES:
        return PublicErrorMessage.KNOWLEDGE_SEARCH_FAILED
    try:
        body = response.json()
    except ValueError:
        return PublicErrorMessage.KNOWLEDGE_SEARCH_REJECTED
    code = body.get("code") if isinstance(body, dict) else None
    if not isinstance(code, str):
        return PublicErrorMessage.KNOWLEDGE_SEARCH_REJECTED
    return _REJECTION_MESSAGES_BY_CODE.get(code, PublicErrorMessage.KNOWLEDGE_SEARCH_REJECTED)


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
        outcome = await client.search_with_usage(target, query, timeout=timeout)

    except Exception as error:
        # The model reads the tool result and the session's viewers the live event, so
        # both get a fixed text: the client's own quotes the knowledge service's internal
        # URL. The reference ties that text to this log line. A client error is the
        # target's state (a deleted or unindexed knowledge base), not a service fault.
        correlation_id = new_error_correlation_id()
        if isinstance(error, httpx.HTTPStatusError) and error.response.is_client_error:
            log_level = "WARNING"
            message = _client_error_message(error.response)
        else:
            log_level = "ERROR"
            message = PublicErrorMessage.KNOWLEDGE_SEARCH_FAILED
        logger.log(
            log_level,
            "knowledge search failed rag_id={} rag_type={} correlation_id={} error={}",
            target.rag_id,
            target.rag_type,
            correlation_id,
            _describe_search_failure(error),
        )
        public_error = build_public_error_message(message, correlation_id)
        await _notify_sink(sink, target, query, [], error=public_error)
        return ToolResult(tool_call_id="", content=public_error, is_error=True)

    result = outcome.result
    await _notify_sink(sink, target, query, result, usage=outcome.usage)

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
