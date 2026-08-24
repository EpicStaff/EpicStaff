"""A failed search publishes a response, so the caller sees an error not a timeout.

Returning without publishing leaves crew waiting out its full search timeout,
which is how the api_key regression presented as a flow timeout rather than an
error. The payload must validate against BaseKnowledgeSearchMessageResponse,
because crew's receiver calls model_validate on it -- an unparseable payload
would time out just as silently.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import main
from src.shared.models import BaseKnowledgeSearchMessageResponse, NaiveRagSearchConfig


async def _failing_search(**overrides):
    redis_service = MagicMock(async_publish=AsyncMock())

    with patch.object(
        main.collection_processor_service, "search", side_effect=RuntimeError("boom")
    ):
        await main.execute_search(
            rag_id=1,
            rag_type="naive",
            collection_id=2,
            uuid=overrides.pop("uuid", "u-1"),
            query="q",
            rag_search_config=NaiveRagSearchConfig(),
            redis_service=redis_service,
            response_channel="knowledge:search:response",
            semaphore=asyncio.Semaphore(1),
            **overrides,
        )
    return redis_service


@pytest.mark.asyncio
async def test_a_failing_search_publishes_a_response():
    redis_service = await _failing_search(uuid="u-1")

    redis_service.async_publish.assert_awaited_once()
    payload = redis_service.async_publish.await_args.args[1]
    assert payload["uuid"] == "u-1"
    assert payload["results"] == []


@pytest.mark.asyncio
async def test_the_failure_payload_validates_for_the_caller():
    """Crew calls model_validate on this; an invalid payload times out silently."""
    redis_service = await _failing_search(uuid="u-2")

    payload = redis_service.async_publish.await_args.args[1]
    validated = BaseKnowledgeSearchMessageResponse.model_validate(payload)

    assert validated.uuid == "u-2"
    assert validated.error is not None


@pytest.mark.asyncio
async def test_the_failure_response_carries_no_credential():
    redis_service = await _failing_search(
        uuid="u-3", embedder_api_key="sk-must-not-leak"
    )

    payload = redis_service.async_publish.await_args.args[1]
    assert "sk-must-not-leak" not in str(payload)


@pytest.mark.asyncio
async def test_a_successful_search_publishes_no_error():
    redis_service = MagicMock(async_publish=AsyncMock())
    ok = {"uuid": "u-4", "results": ["chunk"]}

    with patch.object(main.collection_processor_service, "search", return_value=ok):
        await main.execute_search(
            rag_id=1,
            rag_type="naive",
            collection_id=2,
            uuid="u-4",
            query="q",
            rag_search_config=NaiveRagSearchConfig(),
            redis_service=redis_service,
            response_channel="knowledge:search:response",
            semaphore=asyncio.Semaphore(1),
        )

    payload = redis_service.async_publish.await_args.args[1]
    assert payload == ok
