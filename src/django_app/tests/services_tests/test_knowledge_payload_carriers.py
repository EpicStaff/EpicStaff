"""The knowledge payloads carry credentials by the <field>_secret_id convention.

A carrier field must be excluded from every dump, so no Secret id reaches
Session.graph_schema or a Redis payload, and every carrier must have its paired
plaintext slot or SecretResolver raises.
"""

from src.shared.models.agents import AgentData, RealtimeAgentChatData
from src.shared.models.knowledge import (
    BaseKnowledgeSearchMessage,
    ProcessRagIndexingMessage,
)

CARRIERS = [
    (ProcessRagIndexingMessage, "embedder_api_key_secret_id", "embedder_api_key"),
    (ProcessRagIndexingMessage, "llm_api_key_secret_id", "llm_api_key"),
    (AgentData, "rag_embedder_api_key_secret_id", "rag_embedder_api_key"),
    (RealtimeAgentChatData, "rag_embedder_api_key_secret_id", "rag_embedder_api_key"),
]


def test_every_carrier_has_its_plaintext_slot():
    for model, carrier, plaintext in CARRIERS:
        assert carrier in model.model_fields, f"{model.__name__}.{carrier}"
        assert plaintext in model.model_fields, f"{model.__name__}.{plaintext}"


def test_every_carrier_is_excluded_from_dumps():
    for model, carrier, _ in CARRIERS:
        assert (
            model.model_fields[carrier].exclude is True
        ), f"{model.__name__}.{carrier} must be Field(exclude=True)"


def test_carrier_id_never_appears_in_a_dump():
    message = ProcessRagIndexingMessage(
        rag_id=1,
        rag_type="graph",
        collection_id=2,
        embedder_api_key_secret_id=7,
        llm_api_key_secret_id=8,
    )
    dumped = message.model_dump()
    assert "embedder_api_key_secret_id" not in dumped
    assert "llm_api_key_secret_id" not in dumped
    assert dumped["embedder_api_key"] is None


def test_the_search_message_has_no_carrier():
    """Crew and realtime hold plaintext already; knowledge could never resolve an id."""
    assert "embedder_api_key" in BaseKnowledgeSearchMessage.model_fields
    assert "embedder_api_key_secret_id" not in BaseKnowledgeSearchMessage.model_fields


def test_the_search_message_defaults_to_no_credential():
    message = BaseKnowledgeSearchMessage(
        collection_id=1,
        rag_id=2,
        rag_type="naive",
        uuid="u",
        query="q",
        rag_search_config={"rag_type": "naive"},
    )
    assert message.embedder_api_key is None
