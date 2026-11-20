import json

import httpx
import pytest

from clients.knowledge import KnowledgeClient
from foundation.transport.http import ClientNotFoundError, ClientTimeoutError
from src.shared.enums.knowledge_new import RAGStrategy
from src.shared.models import NaiveSearchConfig


pytestmark = pytest.mark.asyncio

BASE_URL = "http://knowledge.test:8100"


def _client(handler) -> KnowledgeClient:
    return KnowledgeClient(base_url=BASE_URL, transport=httpx.MockTransport(handler))


async def _search(client: KnowledgeClient, **overrides):
    arguments = {
        "strategy": RAGStrategy.NAIVE,
        "rag_id": 2,
        "query": "q",
        "search_config": NaiveSearchConfig(search_limit=3, similarity_threshold=0.2),
        "timeout": 5.0,
        "embedding_api_key": "sk-emb",
        "llm_api_key": None,
    }
    return await client.search_with_usage(**{**arguments, **overrides})


async def test_search_sends_extra_headers_with_the_api_keys():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"result": []})

    client = _client(handler)
    await _search(
        client,
        embedding_extra_headers={"X-Emb": "emb-resolved"},
        llm_extra_headers={"X-Llm": "llm-resolved"},
    )

    assert seen["body"]["embedding_api_key"] == "sk-emb"
    assert seen["body"]["embedding_extra_headers"] == {"X-Emb": "emb-resolved"}
    assert seen["body"]["llm_extra_headers"] == {"X-Llm": "llm-resolved"}


async def test_search_without_extra_headers_sends_empty_objects():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"result": []})

    client = _client(handler)
    await _search(client)

    assert seen["body"]["embedding_extra_headers"] == {}
    assert seen["body"]["llm_extra_headers"] == {}


async def test_search_with_usage_returns_the_embedding_usage_knowledge_new_reports():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"result": [], "usage": {"embedding_tokens": 15, "embedding_cost_usd": 0.0003}},
        )

    client = _client(handler)
    outcome = await client.search_with_usage(
        strategy=RAGStrategy.NAIVE,
        rag_id=2,
        query="q",
        search_config=NaiveSearchConfig(search_limit=3, similarity_threshold=0.2),
        timeout=5.0,
        embedding_api_key="sk-emb",
        llm_api_key=None,
    )

    assert outcome.result == []
    assert outcome.usage.embedding_tokens == 15
    assert outcome.usage.embedding_cost_usd == 0.0003


async def test_search_with_usage_defaults_to_no_usage_for_a_response_without_it():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"result": "an answer"})

    client = _client(handler)
    outcome = await client.search_with_usage(
        strategy=RAGStrategy.NAIVE,
        rag_id=2,
        query="q",
        search_config=NaiveSearchConfig(search_limit=3, similarity_threshold=0.2),
        timeout=5.0,
        embedding_api_key="sk-emb",
        llm_api_key=None,
    )

    assert outcome.result == "an answer"
    assert outcome.usage.embedding_tokens == 0


async def test_search_goes_to_the_configured_base_url():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"result": []})

    await _search(_client(handler))

    assert seen["url"] == "http://knowledge.test:8100/rags/naive/2/search/"


async def test_read_timeout_raises_client_timeout_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("knowledge_new is slow", request=request)

    with pytest.raises(ClientTimeoutError):
        await _search(_client(handler))


async def test_error_status_raises_the_typed_client_error_with_the_response():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"code": "not_found", "detail": "RAG 2 not found"})

    with pytest.raises(ClientNotFoundError) as raised:
        await _search(_client(handler))

    assert raised.value.response.status_code == 404
