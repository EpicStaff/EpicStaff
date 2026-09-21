"""The agent payload carries the RAG embedder's Secret id, so crew and realtime
receive plaintext without ever holding a Secret id or a decryption key.

Crew and realtime publish the knowledge search message, and neither can decrypt.
Django resolves this carrier inside publish_session_data / publish_realtime_agent_chat.
"""

import pytest

from tables.models import Agent
from tables.models.embedding_models import EmbeddingConfig, EmbeddingModel
from tables.models.knowledge_models.collection_models import (
    BaseRagType,
    SourceCollection,
)
from tables.models.knowledge_models.naive_rag_models import NaiveRag
from tables.models.rbac_models import Organization
from tables.services.rag_assignment_service import RagAssignmentService
from tables.services.secrets import secret_service


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Org ConverterRagCreds")


@pytest.fixture
def collection(db, org):
    return SourceCollection.objects.create(
        collection_name="ConverterRagCreds Collection", user_id="test_user", org=org
    )


def _embedder(*, org, secret, custom_name):
    model = EmbeddingModel.objects.create(name=f"model-{custom_name}", org=org)
    return EmbeddingConfig.objects.create(
        custom_name=custom_name, model=model, api_key_secret=secret, org=org
    )


def _agent_with_naive_rag(*, org, collection, embedder):
    base_rag = BaseRagType.objects.create(
        source_collection=collection, rag_type=BaseRagType.RagType.NAIVE
    )
    naive_rag = NaiveRag.objects.create(
        base_rag_type=base_rag,
        embedder=embedder,
        rag_status=NaiveRag.NaiveRagStatus.NEW,
    )
    agent = Agent.objects.create(
        role="Research Agent",
        goal="Research",
        backstory="Researcher",
        knowledge_collection=collection,
        org=org,
    )
    RagAssignmentService.assign_rag_to_agent(agent, "naive", naive_rag.naive_rag_id)
    return agent


@pytest.mark.django_db
def test_an_agent_with_a_naive_rag_reports_its_embedder_secret_id(org, collection):
    secret = secret_service.create(text="sk-emb", org=org, name="emb-conv")
    embedder = _embedder(org=org, secret=secret, custom_name="conv-emb")

    agent = _agent_with_naive_rag(org=org, collection=collection, embedder=embedder)

    assert agent.get_rag_embedder_secret_id() == secret.pk


@pytest.mark.django_db
def test_an_agent_without_a_rag_reports_none(org):
    agent = Agent.objects.create(role="No RAG Agent", goal="G", backstory="B", org=org)

    assert agent.get_rag_embedder_secret_id() is None


@pytest.mark.django_db
def test_a_rag_whose_embedder_has_no_secret_reports_none(org, collection):
    embedder = _embedder(org=org, secret=None, custom_name="conv-emb-nosecret")

    agent = _agent_with_naive_rag(org=org, collection=collection, embedder=embedder)

    assert agent.get_rag_embedder_secret_id() is None


@pytest.mark.django_db
def test_the_secret_id_lookup_is_a_single_query(
    org, collection, django_assert_num_queries
):
    """One query per agent: select_related joins the embedder hop."""
    secret = secret_service.create(text="sk-emb-q", org=org, name="emb-queries")
    embedder = _embedder(org=org, secret=secret, custom_name="conv-emb-queries")
    agent = _agent_with_naive_rag(org=org, collection=collection, embedder=embedder)

    with django_assert_num_queries(1):
        secret_id = agent.get_rag_embedder_secret_id()

    assert secret_id == secret.pk
