"""Crew forwards the embedder credential Django resolved for it.

Crew has no SECRET_KEY, so it can only pass along the plaintext it was given in
AgentData; the knowledge service cannot resolve a Secret id itself.
"""

from unittest.mock import MagicMock, patch

from services.knowledge_search_service import KnowledgeSearchService


def _search_call_kwargs(service, **overrides):
    """Run one knowledge search against a mocked KnowledgeClient and return the
    kwargs `KnowledgeClient.search(...)` was called with.

    `KnowledgeSearchService.search_knowledges` builds its own `KnowledgeClient`
    (`with KnowledgeClient() as client:`), so that class is patched at its
    import site rather than going through `service.redis_service`.
    """
    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.search.return_value = []

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

    return mock_client.search.call_args.kwargs


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
