"""A failed knowledge search returns a fixed message, never the exception text.

The return value becomes the tool result the provider hands to the model, so
anything in it leaves the service.
"""

from unittest.mock import AsyncMock

import pytest

from tests.conftest import PUBLIC_ERROR_REFERENCE, SECRET_SENTINEL
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

    assert SECRET_SENTINEL not in result
    assert "knowledge:8000" not in result
    assert result.startswith("Knowledge search failed")
    assert PUBLIC_ERROR_REFERENCE.search(result)


@pytest.mark.asyncio
async def test_failed_search_logs_detail_under_the_returned_correlation_id(captured_log_messages):
    result = await _failing_executor().execute(query="q")

    correlation_id = PUBLIC_ERROR_REFERENCE.search(result).group(1)
    matching_logs = [message for message in captured_log_messages if correlation_id in message]
    assert len(matching_logs) == 1
    assert SECRET_SENTINEL in matching_logs[0]
