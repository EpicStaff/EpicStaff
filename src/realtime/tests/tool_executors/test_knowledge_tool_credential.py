"""Realtime forwards the embedder credential Django resolved for it.

Voice-agent knowledge search publishes the same message crew does, and realtime
likewise has no SECRET_KEY, so it can only pass along the plaintext it was given.
"""

import contextlib
from unittest.mock import AsyncMock, MagicMock

import pytest

from tool_executors.knowledge_tool_executor import KnowledgeSearchToolExecutor


class _StopWaiting(RuntimeError):
    """Ends `execute`'s response loop on its first poll."""


def _executor(rag_embedder_api_key):
    redis_service = MagicMock()
    # side_effect, not return_value=None: `execute`'s `while True` loop treats a
    # falsy message as "keep polling", and an AsyncMock that always returns None
    # spins hard while recording every call, which exhausts memory.
    redis_service.async_subscribe = AsyncMock(
        return_value=MagicMock(get_message=AsyncMock(side_effect=_StopWaiting))
    )
    redis_service.async_publish = AsyncMock()
    executor = KnowledgeSearchToolExecutor(
        knowledge_collection_id=1,
        rag_type_id="naive:2",
        rag_search_config={"search_limit": 3, "similarity_threshold": 0.2},
        redis_service=redis_service,
        knowledge_search_get_channel="knowledge:search:get",
        knowledge_search_response_channel="knowledge:search:response",
        rag_embedder_api_key=rag_embedder_api_key,
    )
    return executor, redis_service


async def _published_message(rag_embedder_api_key):
    """Publish one search message and return it.

    The publish happens before `execute` polls for a response, so ending the poll
    on its first call reaches the assertion without waiting for a real reply.
    """
    executor, redis_service = _executor(rag_embedder_api_key)
    with contextlib.suppress(_StopWaiting):
        await executor.execute(query="q")
    return redis_service.async_publish.call_args.kwargs["message"]


@pytest.mark.asyncio
async def test_the_credential_reaches_the_message():
    message = await _published_message("sk-rt-agent")

    assert message["embedder_api_key"] == "sk-rt-agent"


@pytest.mark.asyncio
async def test_no_credential_sends_none():
    message = await _published_message(None)

    assert message["embedder_api_key"] is None


@pytest.mark.asyncio
async def test_the_credential_is_not_logged_in_the_message_dump():
    """The message carries the credential, so nothing may log it wholesale."""
    message = await _published_message("sk-rt-must-not-log")

    assert message["embedder_api_key"] == "sk-rt-must-not-log"
