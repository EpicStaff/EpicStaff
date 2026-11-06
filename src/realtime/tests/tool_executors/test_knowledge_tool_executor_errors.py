"""A failed knowledge search returns a fixed message, never the exception text.

The return value becomes the tool result the provider hands to the model, so
anything in it leaves the service.
"""

from unittest.mock import AsyncMock

import pytest
from loguru import logger

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


@pytest.fixture
def error_records():
    records: list[dict] = []
    sink_id = logger.add(lambda message: records.append(message.record), level="ERROR")
    yield records
    logger.remove(sink_id)


@pytest.mark.asyncio
async def test_failed_search_logs_the_raw_error_at_error_under_the_cited_reference(error_records):
    result = await _failing_executor().execute(query="q")

    reference = PUBLIC_ERROR_REFERENCE.search(result).group(1)
    assert SECRET_SENTINEL not in result
    (record,) = error_records
    assert record["message"].startswith(f"(reference: {reference}) Knowledge search failed")
    assert SECRET_SENTINEL in record["message"]
