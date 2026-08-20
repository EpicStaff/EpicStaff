import pytest

from utils.knowledge_utils import knowledge_search


@pytest.mark.skip
@pytest.mark.asyncio
async def test_knowledges(collection_id, redis_service):
    """Knowledges created in 'collection_id' fixture"""
    test_query = "What makes MYM different from other logistics platforms?"

    # TODO: Knowledge status is unchangable for now.
    # Should rewrite this test after fulfilling knowledge status management.
    results = await knowledge_search(
        knowledge_collection_id=collection_id,
        query=test_query,
        redis_service=redis_service,
    )

    # Assertions
    assert results is not None
    assert isinstance(results, list)
    str_results = "\n".join(results)
    assert (
        "A secure and user-friendly platform designed for businesses of all sizes."
        in str_results
    )
