"""Realtime graph-RAG knowledge search never threaded an LLM API key through
to knowledge_new — only the embedder key was resolved. GraphSearchOrchestrator
unconditionally sets the completion model's `api_key` from whatever
`llm_api_key` it receives, so a naive-RAG-shaped resolution (embedder only)
made every graph RAG search through realtime fail with
`litellm.exceptions.InternalServerError: Missing credentials`.

These tests pin down that `RealtimeSurfaceService._resolve_graph_rag` now also
resolves the GraphRag's LLM secret id, and that `_resolve_naive_rag` leaves it
`None` (naive RAG has no LLM call to key).
"""

import pytest

from tables.models.embedding_models import EmbeddingConfig, EmbeddingModel
from tables.models.knowledge_models.collection_models import (
    BaseRagType,
    SourceCollection,
)
from tables.models.knowledge_models.graphrag_models import GraphRag
from tables.models.knowledge_models.naive_rag_models import NaiveRag
from tables.models.llm_models import LLMConfig, LLMModel
from rbac.models import Organization
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
        user_id="test_user",
        org=org,
    )


@pytest.fixture
def resolver():
    return RealtimeSurfaceService(converter_service=ConverterService())


def _embedder(*, org, secret=None):
    model = EmbeddingModel.objects.create(name="embedder-model", org=org)
    return EmbeddingConfig.objects.create(
        custom_name="embedder-cfg", model=model, api_key_secret=secret, org=org
    )


def _llm_config(*, org, secret=None):
    model = LLMModel.objects.create(name="llm-model", org=org)
    return LLMConfig.objects.create(
        custom_name="llm-cfg", model=model, api_key_secret=secret, org=org
    )


@pytest.mark.django_db
def test_graph_rag_resolves_both_embedder_and_llm_secret_ids(resolver, org, collection):
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

    result = resolver._resolve_graph_rag(
        collection.pk, {"graph_basic_search_config": {}}
    )

    assert result.rag_type_id.startswith("graph:")
    assert result.rag_embedder_api_key_secret_id == embedder_secret.pk
    assert result.rag_llm_api_key_secret_id == llm_secret.pk


@pytest.mark.django_db
def test_graph_rag_without_llm_config_reports_none(resolver, org, collection):
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

    result = resolver._resolve_graph_rag(
        collection.pk, {"graph_basic_search_config": {}}
    )

    assert result.rag_llm_api_key_secret_id is None


@pytest.mark.django_db
def test_naive_rag_never_reports_an_llm_secret_id(resolver, org, collection):
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

    result = resolver._resolve_naive_rag(
        collection.pk, {"search_limit": 5, "similarity_threshold": 0.5}
    )

    assert result.rag_type_id.startswith("naive:")
    assert result.rag_embedder_api_key_secret_id == embedder_secret.pk
    assert result.rag_llm_api_key_secret_id is None
