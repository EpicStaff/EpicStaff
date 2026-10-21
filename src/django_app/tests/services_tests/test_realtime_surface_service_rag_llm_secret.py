"""Realtime graph-RAG knowledge search never threaded an LLM API key through
to knowledge_new — only the embedder key was resolved. GraphSearchOrchestrator
unconditionally sets the completion model's `api_key` from whatever
`llm_api_key` it receives, so a naive-RAG-shaped resolution (embedder only)
made every graph RAG search through realtime fail with
`litellm.exceptions.InternalServerError: Missing credentials`.

These tests pin down that `RealtimeSurfaceService.resolve` resolves a graph
RAG's LLM secret id too, and leaves it `None` for naive RAG (no LLM call to key).
"""

import pytest

from agents.models import AgentDefinition, Surface
from agents.models.agent_models import AgentDefaultSurface, SurfacePlace
from agents.models.surface_models import (
    SurfaceGraphBasicSearchConfig,
    SurfaceKnowledge,
    SurfaceNaiveSearchConfig,
)

from tables.models.embedding_models import EmbeddingConfig, EmbeddingModel
from tables.models.knowledge_models.collection_models import (
    BaseRagType,
    SourceCollection,
)
from tables.models.knowledge_models.graphrag_models import GraphRag
from tables.models.knowledge_models.naive_rag_models import NaiveRag
from tables.models.llm_models import LLMConfig, LLMModel
from django.contrib.auth import get_user_model
from rbac.models import Organization, OrganizationUser, Role
from tables.services.converter_service import ConverterService
from tables.services.realtime_surface_service import RealtimeSurfaceService
from tables.services.secrets import secret_service


@pytest.fixture
def org(db):
    return Organization.objects.create(name="RealtimeSurfaceRagLlmSecret Org")


@pytest.fixture
def collection(db, org):
    return SourceCollection.objects.create(
        collection_name="RealtimeSurfaceRagLlmSecret Collection",
        org=org,
    )


def _resolve_for_realtime(org, collection, rag_type):
    """Give a realtime agent a surface searching `collection`, then resolve it."""
    agent = AgentDefinition.objects.create(
        org=org, name="rag-secret-agent", instruction_list=[{"name": "Instruction_1.md", "content": "x"}]
    )
    surface = Surface.objects.create(org=org, name="rag-secret-surface", instructions="")
    knowledge = SurfaceKnowledge.objects.create(surface=surface, collection=collection)
    if rag_type == "naive":
        SurfaceNaiveSearchConfig.objects.create(surface_knowledge=knowledge, search_limit=5, similarity_threshold="0.5")
    else:
        SurfaceGraphBasicSearchConfig.objects.create(surface_knowledge=knowledge, prompt="basic prompt", k=7)
    AgentDefaultSurface.objects.create(agent_definition=agent, surface=surface, place=SurfacePlace.REALTIME)
    return RealtimeSurfaceService(converter_service=ConverterService()).resolve(agent)


def _approver(org):
    """An Org Admin (holds secrets:USE) of `org`, who approved the configs' secret binding.

    The models below belong to the org, so they are custom destinations: their configs'
    keys are injected only with such an approver.
    """
    user, created = get_user_model().objects.get_or_create(email=f"approver-{org.pk}@example.com")
    if created:
        OrganizationUser.objects.create(
            user=user, org=org, role=Role.objects.get(name="Org Admin", is_built_in=True, org__isnull=True)
        )
    return user


def _embedder(*, org, secret=None):
    model = EmbeddingModel.objects.create(name="embedder-model", org=org)
    return EmbeddingConfig.objects.create(
        custom_name="embedder-cfg",
        model=model,
        api_key_secret=secret,
        org=org,
        secret_binding_approved_by=_approver(org),
    )


def _llm_config(*, org, secret=None):
    model = LLMModel.objects.create(name="llm-model", org=org)
    return LLMConfig.objects.create(
        custom_name="llm-cfg",
        model=model,
        api_key_secret=secret,
        org=org,
        secret_binding_approved_by=_approver(org),
    )


@pytest.mark.django_db
def test_graph_rag_resolves_both_embedder_and_llm_secret_ids(org, collection):
    embedder_secret = secret_service.create(text="sk-emb", org=org, name="emb-graph")
    llm_secret = secret_service.create(text="sk-llm", org=org, name="llm-graph")
    embedder = _embedder(org=org, secret=embedder_secret)
    llm = _llm_config(org=org, secret=llm_secret)
    base_rag = BaseRagType.objects.create(
        source_collection=collection, rag_type=BaseRagType.RagType.GRAPH
    )
    GraphRag.objects.create(
        base_rag_type=base_rag,
        embedder=embedder,
        llm=llm,
        rag_status=GraphRag.GraphRagStatus.COMPLETED,
    )

    result = _resolve_for_realtime(org, collection, "graph")

    assert result.rag_type_id.startswith("graph:")
    assert result.rag_embedder_api_key_secret_id == embedder_secret.pk
    assert result.rag_llm_api_key_secret_id == llm_secret.pk


@pytest.mark.django_db
def test_graph_rag_without_llm_config_reports_none(org, collection):
    embedder_secret = secret_service.create(text="sk-emb2", org=org, name="emb-graph2")
    embedder = _embedder(org=org, secret=embedder_secret)
    base_rag = BaseRagType.objects.create(
        source_collection=collection, rag_type=BaseRagType.RagType.GRAPH
    )
    GraphRag.objects.create(
        base_rag_type=base_rag,
        embedder=embedder,
        llm=None,
        rag_status=GraphRag.GraphRagStatus.COMPLETED,
    )

    result = _resolve_for_realtime(org, collection, "graph")

    assert result.rag_llm_api_key_secret_id is None


@pytest.mark.django_db
def test_naive_rag_never_reports_an_llm_secret_id(org, collection):
    """Naive RAG has no LLM call — the LLM secret id must stay None even
    though naive_rag_models.NaiveRag has no `llm` field at all."""
    embedder_secret = secret_service.create(text="sk-emb3", org=org, name="emb-naive")
    embedder = _embedder(org=org, secret=embedder_secret)
    base_rag = BaseRagType.objects.create(
        source_collection=collection, rag_type=BaseRagType.RagType.NAIVE
    )
    NaiveRag.objects.create(
        base_rag_type=base_rag,
        embedder=embedder,
        rag_status=NaiveRag.NaiveRagStatus.COMPLETED,
    )

    result = _resolve_for_realtime(org, collection, "naive")

    assert result.rag_type_id.startswith("naive:")
    assert result.rag_embedder_api_key_secret_id == embedder_secret.pk
    assert result.rag_llm_api_key_secret_id is None
