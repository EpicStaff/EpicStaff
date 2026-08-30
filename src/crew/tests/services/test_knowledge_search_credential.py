"""Crew forwards the embedder credential Django resolved for it.

Crew has no SECRET_KEY, so it can only pass along the plaintext it was given in
AgentData; the knowledge service cannot resolve a Secret id itself.
"""

import contextlib
from unittest.mock import MagicMock

from services.knowledge_search_service import KnowledgeSearchService


def _published_message(service, **overrides):
    """Publish one search message and return it.

    The message is published before the response wait, so `timeout=0` reaches the
    assertion via the raised TimeoutError rather than a returned value.
    """
    service.redis_service = MagicMock()
    with contextlib.suppress(TimeoutError):
        service.search_knowledges(
            sender="ag",
            knowledge_collection_id=1,
            rag_type_id="naive:2",
            query="q",
            rag_search_config={"search_limit": 3, "similarity_threshold": 0.2},
            timeout=0,
            **overrides,
        )
    return service.redis_service.publish.call_args.kwargs["message"]


def test_the_instance_credential_reaches_the_message():
    service = KnowledgeSearchService(
        redis_service=MagicMock(), rag_embedder_api_key="sk-from-agent"
    )
    assert _published_message(service)["embedder_api_key"] == "sk-from-agent"


def test_an_explicit_credential_wins_over_the_instance_one():
    service = KnowledgeSearchService(
        redis_service=MagicMock(), rag_embedder_api_key="sk-instance"
    )
    message = _published_message(service, rag_embedder_api_key="sk-explicit")
    assert message["embedder_api_key"] == "sk-explicit"


def test_no_credential_sends_none():
    service = KnowledgeSearchService(redis_service=MagicMock())
    assert _published_message(service)["embedder_api_key"] is None
