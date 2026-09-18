"""Realtime forwards the embedder credential Django resolved for it.

Voice-agent knowledge search calls knowledge_new the same way crew does, and
realtime likewise has no SECRET_KEY, so it can only pass along the plaintext
it was given.
"""

from unittest.mock import AsyncMock

import pytest

from tool_executors.knowledge_tool_executor import KnowledgeSearchToolExecutor


def _executor(rag_embedder_api_key):
    knowledge_client = AsyncMock()
    knowledge_client.search = AsyncMock(return_value=[])
    executor = KnowledgeSearchToolExecutor(
        knowledge_collection_id=1,
        rag_type_id="naive:2",
        rag_search_config={"search_limit": 3, "similarity_threshold": 0.2},
        knowledge_client=knowledge_client,
        rag_embedder_api_key=rag_embedder_api_key,
    )
    return executor, knowledge_client


async def _searched_target(rag_embedder_api_key):
    """Run one search and return the `KnowledgeSearchTarget` passed to the client."""
    executor, knowledge_client = _executor(rag_embedder_api_key)
    await executor.execute(query="q")
    args, kwargs = knowledge_client.search.call_args
    return args[0]


@pytest.mark.asyncio
async def test_the_credential_reaches_the_search_target():
    target = await _searched_target("sk-rt-agent")

    assert target.embedder_api_key == "sk-rt-agent"


@pytest.mark.asyncio
async def test_no_credential_sends_none():
    target = await _searched_target(None)

    assert target.embedder_api_key is None
