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
    return client.search(**{**arguments, **overrides})


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
