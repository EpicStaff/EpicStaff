"""Crew forwards the embedder credential Django resolved for it.

Crew has no SECRET_KEY, so it can only pass along the plaintext it was given in
AgentData; the knowledge service cannot resolve a Secret id itself.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.knowledge_search_service import KnowledgeSearchService
from src.shared.models import SearchOutcome


def _search_call_kwargs(instance_key: str | None = None, **overrides):
    """Run one knowledge search against a mocked KnowledgeClient and return the
    kwargs `KnowledgeClient.search_with_usage(...)` was called with.
    """
    knowledge_client = MagicMock()
    knowledge_client.search_with_usage = AsyncMock(return_value=SearchOutcome(result=[]))
    service = KnowledgeSearchService(
        redis_service=MagicMock(),
        knowledge_client=knowledge_client,
        rag_embedder_api_key=instance_key,
    )

    asyncio.run(
        service.search_knowledges(
            sender="ag",
            knowledge_collection_id=1,
            rag_type_id="naive:2",
            query="q",
            rag_search_config={"search_limit": 3, "similarity_threshold": 0.2},
            **overrides,
        )
    )

    return knowledge_client.search_with_usage.call_args.kwargs


@pytest.mark.parametrize(
    ("instance_key", "explicit_key", "sent_key"),
    [
        ("sk-from-agent", None, "sk-from-agent"),
        ("sk-instance", "sk-explicit", "sk-explicit"),
        (None, None, None),
    ],
    ids=["instance-credential", "explicit-wins", "no-credential"],
)
def test_the_resolved_embedder_credential_is_sent_with_the_search(instance_key, explicit_key, sent_key):
    overrides = {"rag_embedder_api_key": explicit_key} if explicit_key else {}

    assert _search_call_kwargs(instance_key, **overrides)["embedding_api_key"] == sent_key


def test_extra_headers_and_connections_reach_the_client():
    kwargs = _search_call_kwargs(
        rag_embedder_extra_headers={"X-Emb": "emb-resolved"},
        rag_llm_extra_headers={"X-Llm": "llm-resolved"},
        rag_embedder_connection={"api_base": "http://emb-gateway/v1"},
        rag_embedder_parameters={"dimensions": 256},
        rag_llm_connection={"aws_region_name": "eu-west-1"},
        rag_llm_parameters={"temperature": 0.1},
    )
    assert kwargs["embedding_extra_headers"] == {"X-Emb": "emb-resolved"}
    assert kwargs["llm_extra_headers"] == {"X-Llm": "llm-resolved"}
    assert kwargs["embedding_connection"] == {"api_base": "http://emb-gateway/v1"}
    assert kwargs["embedding_parameters"] == {"dimensions": 256}
    assert kwargs["llm_connection"] == {"aws_region_name": "eu-west-1"}
    assert kwargs["llm_parameters"] == {"temperature": 0.1}


def test_no_extra_headers_sends_none():
    kwargs = _search_call_kwargs()
    assert kwargs["embedding_extra_headers"] is None
    assert kwargs["llm_extra_headers"] is None
