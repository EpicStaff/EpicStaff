"""
Tests for KnowledgeClient.

Mocks redis.asyncio so no real Redis is needed.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.knowledge.client import KnowledgeClient
from app.knowledge.target import KnowledgeSearchTarget
from shared.models.knowledge import (
    BaseKnowledgeSearchMessageResponse,
    KnowledgeChunkResponse,
    NaiveRagSearchConfig,
)


def _make_client() -> KnowledgeClient:
    return KnowledgeClient(
        host="127.0.0.1",
        port=6379,
        password=None,
        request_channel="knowledge:search:get",
        response_channel="knowledge:search:response",
    )


def _make_target(unique_name: str = "naive:1") -> KnowledgeSearchTarget:
    return KnowledgeSearchTarget(
        collection_id=10,
        rag_id=1,
        rag_type="naive",
        search_config=NaiveRagSearchConfig(),
    )


def _response_message(search_uuid: str) -> dict:
    payload = BaseKnowledgeSearchMessageResponse(
        rag_id=1,
        rag_type="naive",
        collection_id=10,
        uuid=search_uuid,
        retrieved_chunks=1,
        query="hello",
        chunks=[
            KnowledgeChunkResponse(
                chunk_order=0,
                chunk_similarity=0.9,
                chunk_text="relevant content",
                chunk_source="doc.pdf",
            )
        ],
        rag_search_config=NaiveRagSearchConfig(),
    )
    return {"type": "message", "data": payload.model_dump_json().encode()}


async def _make_async_generator(items):
    for item in items:
        yield item


@pytest.fixture
def mock_redis_factory():
    def factory(messages: list[dict] | None = None):
        messages = messages or []
        pubsub = MagicMock()
        pubsub.subscribe = AsyncMock()
        pubsub.close = AsyncMock()
        pubsub.listen = MagicMock(return_value=_make_async_generator(messages))

        redis_mock = MagicMock()
        redis_mock.publish = AsyncMock()
        redis_mock.aclose = AsyncMock()
        redis_mock.pubsub = MagicMock(return_value=pubsub)

        return redis_mock, pubsub

    return factory


async def test_start_subscribes_to_response_channel(mock_redis_factory):
    redis_mock, pubsub = mock_redis_factory()

    with patch("app.knowledge.client.aioredis.Redis", return_value=redis_mock):
        client = _make_client()
        await client.start()

        pubsub.subscribe.assert_called_once_with("knowledge:search:response")

    await client.stop()


async def test_start_is_idempotent(mock_redis_factory):
    redis_mock, pubsub = mock_redis_factory()

    with patch("app.knowledge.client.aioredis.Redis", return_value=redis_mock):
        client = _make_client()
        await client.start()
        await client.start()

        pubsub.subscribe.assert_called_once()

    await client.stop()


async def test_search_publishes_correct_message(mock_redis_factory):
    search_uuid = "test-uuid-1"
    target = _make_target()
    response_msg = _response_message(search_uuid)

    redis_mock, pubsub = mock_redis_factory(
        messages=[
            {"type": "subscribe", "data": 1},
            response_msg,
        ]
    )

    with patch("app.knowledge.client.aioredis.Redis", return_value=redis_mock):
        client = _make_client()
        await client.start()

        with patch("app.knowledge.client.uuid4", return_value=search_uuid):
            result = await asyncio.wait_for(
                client.search(target, "hello", timeout=2.0), timeout=3.0
            )

        redis_mock.publish.assert_called_once()
        call_args = redis_mock.publish.call_args
        assert call_args[0][0] == "knowledge:search:get"

        published = json.loads(call_args[0][1])
        assert published["uuid"] == search_uuid
        assert published["query"] == "hello"
        assert published["collection_id"] == target.collection_id
        assert published["rag_id"] == target.rag_id
        assert published["rag_type"] == "naive"

        assert result.uuid == search_uuid
        assert len(result.chunks) == 1
        assert result.chunks[0].chunk_text == "relevant content"

    await client.stop()


async def test_search_resolves_on_matching_uuid(mock_redis_factory):
    search_uuid = "match-uuid"
    target = _make_target()
    response_msg = _response_message(search_uuid)

    redis_mock, pubsub = mock_redis_factory(messages=[response_msg])

    with patch("app.knowledge.client.aioredis.Redis", return_value=redis_mock):
        client = _make_client()
        await client.start()

        with patch("app.knowledge.client.uuid4", return_value=search_uuid):
            result = await asyncio.wait_for(
                client.search(target, "query", timeout=2.0), timeout=3.0
            )

        assert result.uuid == search_uuid

    await client.stop()


async def test_search_ignores_non_matching_uuid(mock_redis_factory):
    target = _make_target()
    wrong_msg = _response_message("wrong-uuid")

    redis_mock, pubsub = mock_redis_factory(messages=[wrong_msg])

    with patch("app.knowledge.client.aioredis.Redis", return_value=redis_mock):
        client = _make_client()
        await client.start()

        with patch("app.knowledge.client.uuid4", return_value="expected-uuid"):
            with pytest.raises(asyncio.TimeoutError):
                await client.search(target, "query", timeout=0.1)

    await client.stop()


async def test_search_raises_on_timeout(mock_redis_factory):
    target = _make_target()
    redis_mock, pubsub = mock_redis_factory(messages=[])

    async def never_ending():
        while True:
            yield {"type": "subscribe", "data": 1}
            await asyncio.sleep(10)

    pubsub.listen = MagicMock(return_value=never_ending())

    with patch("app.knowledge.client.aioredis.Redis", return_value=redis_mock):
        client = _make_client()
        await client.start()

        with pytest.raises(asyncio.TimeoutError):
            await client.search(target, "query", timeout=0.05)

    await client.stop()


async def test_stop_fails_pending_futures(mock_redis_factory):
    target = _make_target()
    redis_mock, pubsub = mock_redis_factory(messages=[])

    async def never_ending():
        while True:
            yield {"type": "subscribe", "data": 1}
            await asyncio.sleep(10)

    pubsub.listen = MagicMock(return_value=never_ending())

    with patch("app.knowledge.client.aioredis.Redis", return_value=redis_mock):
        client = _make_client()
        await client.start()

        search_task = asyncio.create_task(client.search(target, "query", timeout=10.0))
        await asyncio.sleep(0.01)
        await client.stop()

        with pytest.raises(ConnectionError, match="KnowledgeClient stopped"):
            await search_task


async def test_malformed_message_is_skipped(mock_redis_factory):
    search_uuid = "after-malformed"
    target = _make_target()
    valid_msg = _response_message(search_uuid)
    malformed_msg = {"type": "message", "data": b"not valid json {{{"}

    redis_mock, pubsub = mock_redis_factory(messages=[malformed_msg, valid_msg])

    with patch("app.knowledge.client.aioredis.Redis", return_value=redis_mock):
        client = _make_client()
        await client.start()

        with patch("app.knowledge.client.uuid4", return_value=search_uuid):
            result = await asyncio.wait_for(
                client.search(target, "query", timeout=2.0), timeout=3.0
            )

        assert result.uuid == search_uuid

    await client.stop()


async def test_stop_closes_redis_and_pubsub(mock_redis_factory):
    redis_mock, pubsub = mock_redis_factory()

    with patch("app.knowledge.client.aioredis.Redis", return_value=redis_mock):
        client = _make_client()
        await client.start()
        await client.stop()

        pubsub.close.assert_called_once()
        redis_mock.aclose.assert_called_once()


async def test_wire_message_shape(mock_redis_factory):
    """Wire message must contain collection_id, rag_id, rag_type, uuid, query, rag_search_config."""
    search_uuid = "wire-shape-uuid"
    target = _make_target()
    response_msg = _response_message(search_uuid)

    redis_mock, pubsub = mock_redis_factory(
        messages=[{"type": "subscribe", "data": 1}, response_msg]
    )

    with patch("app.knowledge.client.aioredis.Redis", return_value=redis_mock):
        client = _make_client()
        await client.start()

        with patch("app.knowledge.client.uuid4", return_value=search_uuid):
            await asyncio.wait_for(
                client.search(target, "wire test", timeout=2.0), timeout=3.0
            )

        published = json.loads(redis_mock.publish.call_args[0][1])
        assert "collection_id" in published
        assert "rag_id" in published
        assert "rag_type" in published
        assert "uuid" in published
        assert "query" in published
        assert "rag_search_config" in published
        # embedder must NOT be in the wire message
        assert "embedder" not in published

    await client.stop()
