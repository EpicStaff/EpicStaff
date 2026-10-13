import json

import httpx

from clients.knowledge import KnowledgeClient
from src.shared.enums.knowledge_new import RAGStrategy
from src.shared.models import NaiveSearchConfig


def _client(handler) -> KnowledgeClient:
    client = KnowledgeClient()
    client._client = httpx.Client(
        base_url=KnowledgeClient.HOST, transport=httpx.MockTransport(handler)
    )
    return client


def _search(client: KnowledgeClient, **overrides):
    arguments = {
        "strategy": RAGStrategy.NAIVE,
        "rag_id": 2,
        "query": "q",
        "search_config": NaiveSearchConfig(search_limit=3, similarity_threshold=0.2),
        "timeout": 5.0,
        "embedding_api_key": "sk-emb",
        "llm_api_key": None,
    }
    return client.search_with_usage(**{**arguments, **overrides})


def test_search_sends_extra_headers_with_the_api_keys():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"result": []})

    with _client(handler) as client:
        _search(
            client,
            embedding_extra_headers={"X-Emb": "emb-resolved"},
            llm_extra_headers={"X-Llm": "llm-resolved"},
        )

    assert seen["body"]["embedding_api_key"] == "sk-emb"
    assert seen["body"]["embedding_extra_headers"] == {"X-Emb": "emb-resolved"}
    assert seen["body"]["llm_extra_headers"] == {"X-Llm": "llm-resolved"}


def test_search_without_extra_headers_sends_empty_objects():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"result": []})

    with _client(handler) as client:
        _search(client)

    assert seen["body"]["embedding_extra_headers"] == {}
    assert seen["body"]["llm_extra_headers"] == {}


def test_search_with_usage_returns_the_embedding_usage_knowledge_new_reports():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"result": [], "usage": {"embedding_tokens": 15, "embedding_cost_usd": 0.0003}},
        )

    with _client(handler) as client:
        outcome = client.search_with_usage(
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


def test_search_with_usage_defaults_to_no_usage_for_a_response_without_it():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"result": "an answer"})

    with _client(handler) as client:
        outcome = client.search_with_usage(
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
