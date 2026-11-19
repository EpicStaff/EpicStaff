"""A failed knowledge search returns a fixed message, never the exception text.

The return value becomes the tool result the provider hands to the model, so
anything in it leaves the service.
"""

from unittest.mock import AsyncMock

import pytest

from tests.conftest import SECRET_SENTINEL
from tool_executors.knowledge_tool_executor import KnowledgeSearchToolExecutor


def _failing_executor() -> KnowledgeSearchToolExecutor:
    knowledge_client = AsyncMock()
    knowledge_client.search = AsyncMock(
        side_effect=RuntimeError(f"connect to http://knowledge:8000 failed key={SECRET_SENTINEL}")
    )
    return KnowledgeSearchToolExecutor(
        knowledge_collection_id=1,
        rag_type_id="naive:2",
        rag_search_config={"search_limit": 3, "similarity_threshold": 0.2},
        knowledge_client=knowledge_client,
    )


@pytest.mark.asyncio
async def test_failed_search_result_omits_exception_text():
    result = await _failing_executor().execute(query="q")

    assert result == "The knowledge search failed."


@pytest.mark.asyncio
async def test_failed_search_logs_detail_with_the_rag_id(captured_log_messages):
    await _failing_executor().execute(query="q")

    matching_logs = [message for message in captured_log_messages if SECRET_SENTINEL in message]
    assert len(matching_logs) == 1
    assert "rag_id=2" in matching_logs[0]
