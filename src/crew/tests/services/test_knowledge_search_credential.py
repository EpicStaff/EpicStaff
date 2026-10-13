"""Crew forwards the embedder credential Django resolved for it.

Crew has no SECRET_KEY, so it can only pass along the plaintext it was given in
AgentData; the knowledge service cannot resolve a Secret id itself.
"""

from unittest.mock import MagicMock, patch

from services.knowledge_search_service import KnowledgeSearchService
from src.shared.models import SearchOutcome


def _search_call_kwargs(service, **overrides):
    """Run one knowledge search against a mocked KnowledgeClient and return the
    kwargs `KnowledgeClient.search_with_usage(...)` was called with.

    `KnowledgeSearchService.search_knowledges` builds its own `KnowledgeClient`
    (`with KnowledgeClient() as client:`), so that class is patched at its
    import site rather than going through `service.redis_service`.
    """
    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.search_with_usage.return_value = SearchOutcome(result=[])

    with patch(
        "services.knowledge_search_service.KnowledgeClient", return_value=mock_client
    ):
        service.search_knowledges(
            sender="ag",
            knowledge_collection_id=1,
            rag_type_id="naive:2",
            query="q",
            rag_search_config={"search_limit": 3, "similarity_threshold": 0.2},
            **overrides,
        )

    return mock_client.search_with_usage.call_args.kwargs


def test_the_instance_credential_reaches_the_message():
    service = KnowledgeSearchService(
        redis_service=MagicMock(), rag_embedder_api_key="sk-from-agent"
    )
    assert _search_call_kwargs(service)["embedding_api_key"] == "sk-from-agent"


def test_an_explicit_credential_wins_over_the_instance_one():
    service = KnowledgeSearchService(
        redis_service=MagicMock(), rag_embedder_api_key="sk-instance"
    )
    kwargs = _search_call_kwargs(service, rag_embedder_api_key="sk-explicit")
    assert kwargs["embedding_api_key"] == "sk-explicit"


def test_no_credential_sends_none():
    service = KnowledgeSearchService(redis_service=MagicMock())
    assert _search_call_kwargs(service)["embedding_api_key"] is None


def test_extra_headers_reach_the_client():
    service = KnowledgeSearchService(redis_service=MagicMock())
    kwargs = _search_call_kwargs(
        service,
        rag_embedder_extra_headers={"X-Emb": "emb-resolved"},
        rag_llm_extra_headers={"X-Llm": "llm-resolved"},
    )
    assert kwargs["embedding_extra_headers"] == {"X-Emb": "emb-resolved"}
    assert kwargs["llm_extra_headers"] == {"X-Llm": "llm-resolved"}


def test_no_extra_headers_sends_none():
    service = KnowledgeSearchService(redis_service=MagicMock())
    kwargs = _search_call_kwargs(service)
    assert kwargs["embedding_extra_headers"] is None
    assert kwargs["llm_extra_headers"] is None
