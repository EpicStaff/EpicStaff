"""
Tests for the REST KnowledgeClient.

Uses ``httpx.MockTransport`` so no real knowledge_new service is needed.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.knowledge.client import KnowledgeClient
from app.knowledge.target import KnowledgeSearchTarget
from shared.models.knowledge import (
    GraphRagBasicSearchParams,
    GraphRagSearchConfig,
    NaiveRagSearchConfig,
)

BASE_URL = "http://knowledge_new:8100"


def _naive_target() -> KnowledgeSearchTarget:
    return KnowledgeSearchTarget(
        collection_id=10,
        rag_id=1,
        rag_type="naive",
        search_config=NaiveRagSearchConfig(search_limit=5, similarity_threshold=0.3),
        embedder_api_key="emb-key",
    )


def _graph_target() -> KnowledgeSearchTarget:
    return KnowledgeSearchTarget(
        collection_id=10,
        rag_id=7,
        rag_type="graph",
        search_config=GraphRagSearchConfig(
            search_params=GraphRagBasicSearchParams(prompt="p", k=8)
        ),
        embedder_api_key="emb-key",
        llm_api_key="llm-key",
    )


def _client_with_handler(handler) -> KnowledgeClient:
    client = KnowledgeClient(base_url=BASE_URL)
    client._client = httpx.AsyncClient(
        base_url=BASE_URL, transport=httpx.MockTransport(handler)
    )
    return client


async def test_naive_search_posts_and_parses_chunks():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "result": [
                    {
                        "order": 0,
                        "similarity": 0.9,
                        "text": "relevant content",
                        "source": "doc.pdf",
                    }
                ]
            },
        )

    client = _client_with_handler(handler)
    result = await client.search(_naive_target(), "hello", timeout=2.0)

    assert captured["method"] == "POST"
    assert captured["path"] == "/rags/naive/1/search/"
    assert captured["body"]["query"] == "hello"
    assert captured["body"]["embedding_api_key"] == "emb-key"
    assert captured["body"]["llm_api_key"] is None
    assert captured["body"]["search_config"] == {
        "rag_strategy": "naive",
        "search_limit": 5,
        "similarity_threshold": 0.3,
    }

    assert isinstance(result, list)
    assert result[0].text == "relevant content"
    assert result[0].source == "doc.pdf"

    await client.stop()


async def test_graph_search_maps_method_and_returns_answer():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"result": "the synthesised answer"})

    client = _client_with_handler(handler)
    result = await client.search(_graph_target(), "why", timeout=2.0)

    assert captured["path"] == "/rags/graph/7/search/"
    assert captured["body"]["llm_api_key"] == "llm-key"
    search_config = captured["body"]["search_config"]
    assert search_config["rag_strategy"] == "graph"
    assert search_config["method"] == "basic"
    assert search_config["prompt"] == "p"
    assert search_config["k"] == 8
    assert "search_method" not in search_config

    assert result == "the synthesised answer"

    await client.stop()


async def test_search_raises_on_error_status():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    client = _client_with_handler(handler)
    with pytest.raises(httpx.HTTPStatusError):
        await client.search(_naive_target(), "hello", timeout=2.0)

    await client.stop()


async def test_start_is_idempotent():
    client = KnowledgeClient(base_url=BASE_URL)
    await client.start()
    first = client._client
    await client.start()

    assert client._client is first

    await client.stop()


async def test_stop_closes_client():
    client = KnowledgeClient(base_url=BASE_URL)
    await client.start()
    await client.stop()

    assert client._client is None
