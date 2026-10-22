"""RAG embedder/LLM extra headers travel next to the RAG api keys on every path.

The payloads carry the raw headers, `epicstaff_secret(<name>)` markers included;
SecretResolver fills them only on the published copy, so Session.graph_schema and
any other persisted copy keep the markers.
"""

from unittest.mock import MagicMock

import pytest

from rbac.models import Organization
from tables.models.embedding_models import EmbeddingConfig, EmbeddingModel
from tables.models.graph_models import Graph, KnowledgeNode
from tables.models.knowledge_models.collection_models import (
    BaseRagType,
    DocumentMetadata,
    SourceCollection,
)
from tables.models.knowledge_models.graphrag_models import (
    GraphRag,
    GraphRagDocument,
    GraphRagIndexConfig,
)
from tables.models.knowledge_models.naive_rag_models import NaiveRag
from tables.models.llm_models import LLMConfig, LLMModel
from tables.models.provider import Provider
from tables.services.converter_service import ConverterService
from tables.services.realtime_surface_service import RealtimeSurfaceService
from tables.services.secrets import secret_service
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

EMBEDDER_HEADERS = {"X-Emb-Key": "epicstaff_secret(EMB_GATEWAY)", "X-Trace": "t"}
LLM_HEADERS = {"Authorization": "Bearer epicstaff_secret(LLM_GATEWAY)"}


@pytest.fixture
def org(db):
    return Organization.objects.create(name="RagExtraHeaders Org")


@pytest.fixture
def collection(org):
    return SourceCollection.objects.create(collection_name="Headers KB", org=org)


def _embedder(org, extra_headers=None):
    provider, _ = Provider.objects.get_or_create(name="openai")
    model = EmbeddingModel.objects.create(
        name="emb-model",
        org=org,
        base_url="http://gateway:8080/v1",
        embedding_provider=provider,
    )
    return EmbeddingConfig.objects.create(
        custom_name="emb-cfg", model=model, org=org, extra_headers=extra_headers or {}
    )


def _llm(org, extra_headers=None):
    model = LLMModel.objects.create(name="llm-model", org=org)
    return LLMConfig.objects.create(
        custom_name="llm-cfg", model=model, org=org, extra_headers=extra_headers or {}
    )


def _graph_rag(org, collection):
    base_rag = BaseRagType.objects.create(
        source_collection=collection, rag_type=BaseRagType.RagType.GRAPH
    )
    return GraphRag.objects.create(
        base_rag_type=base_rag,
        embedder=_embedder(org, EMBEDDER_HEADERS),
        llm=_llm(org, LLM_HEADERS),
        rag_status=GraphRag.GraphRagStatus.COMPLETED,
    )


def _naive_rag(org, collection):
    base_rag = BaseRagType.objects.create(
        source_collection=collection, rag_type=BaseRagType.RagType.NAIVE
    )
    return NaiveRag.objects.create(
        base_rag_type=base_rag,
        embedder=_embedder(org, EMBEDDER_HEADERS),
        rag_status=NaiveRag.NaiveRagStatus.COMPLETED,
    )


@pytest.mark.django_db
def test_embedding_config_conversion_carries_raw_extra_headers(org):
    embedder = ConverterService().convert_embedding_config_to_pydantic(
        _embedder(org, EMBEDDER_HEADERS)
    )

    assert embedder.config.extra_headers == EMBEDDER_HEADERS
    assert embedder.config.base_url == "http://gateway:8080/v1"


@pytest.mark.django_db
def test_graph_knowledge_node_carries_embedder_and_llm_headers(org, collection):
    graph_rag = _graph_rag(org, collection)
    node = KnowledgeNode.objects.create(
        graph=Graph.objects.create(org=org, name="headers-flow"),
        source_collection=collection,
        rag_type="graph",
        rag_id=graph_rag.graph_rag_id,
        query="q",
    )

    data = ConverterService().convert_knowledge_node_to_pydantic(
        node, resolver=lambda node_id: "knowledge"
    )

    assert data.embedder_extra_headers == EMBEDDER_HEADERS
    assert data.llm_extra_headers == LLM_HEADERS
    # The dump is what lands in Session.graph_schema: markers, never plaintext.
    dumped = data.model_dump()
    assert dumped["embedder_extra_headers"] == EMBEDDER_HEADERS
    assert dumped["llm_extra_headers"] == LLM_HEADERS


@pytest.mark.django_db
def test_naive_knowledge_node_has_no_llm_headers(org, collection):
    naive_rag = _naive_rag(org, collection)
    node = KnowledgeNode.objects.create(
        graph=Graph.objects.create(org=org, name="naive-headers-flow"),
        source_collection=collection,
        rag_type="naive",
        rag_id=naive_rag.naive_rag_id,
        query="q",
    )

    data = ConverterService().convert_knowledge_node_to_pydantic(
        node, resolver=lambda node_id: "knowledge"
    )

    assert data.embedder_extra_headers == EMBEDDER_HEADERS
    assert data.llm_extra_headers is None


@pytest.mark.django_db
def test_knowledge_node_without_rag_has_no_headers(org):
    node = KnowledgeNode.objects.create(
        graph=Graph.objects.create(org=org, name="no-rag-flow"), query="q"
    )

    data = ConverterService().convert_knowledge_node_to_pydantic(
        node, resolver=lambda node_id: "knowledge"
    )

    assert data.embedder_extra_headers is None
    assert data.llm_extra_headers is None


@pytest.mark.django_db
def test_node_rag_credentials_resolve_the_rag_once(
    org, collection, django_assert_num_queries
):
    secret = secret_service.create(text="sk-emb", org=org, name="EMB_KEY_ONCE")
    graph_rag = _graph_rag(org, collection)
    graph_rag.embedder.api_key_secret = secret
    graph_rag.embedder.save(update_fields=["api_key_secret"])
    node = KnowledgeNode.objects.create(
        graph=Graph.objects.create(org=org, name="once-flow"),
        source_collection=collection,
        rag_type="graph",
        rag_id=graph_rag.graph_rag_id,
        query="q",
    )
    node = KnowledgeNode.objects.select_related("source_collection").get(pk=node.pk)

    # One query for the RAG, one each for the lazily loaded embedder and LLM.
    with django_assert_num_queries(3):
        credentials = ConverterService._node_rag_credentials(node)

    assert credentials.embedder_api_key_secret_id == secret.pk
    assert credentials.llm_api_key_secret_id is None
    assert credentials.embedder_extra_headers == EMBEDDER_HEADERS
    assert credentials.llm_extra_headers == LLM_HEADERS


@pytest.mark.django_db
def test_node_without_rag_has_empty_credentials_and_issues_no_query(
    org, django_assert_num_queries
):
    node = KnowledgeNode.objects.create(
        graph=Graph.objects.create(org=org, name="no-rag-once-flow"), query="q"
    )

    with django_assert_num_queries(0):
        credentials = ConverterService._node_rag_credentials(node)

    assert credentials == (None, None, None, None)


@pytest.mark.django_db
def test_realtime_graph_rag_resolution_carries_headers(org, collection):
    _graph_rag(org, collection)

    result = RealtimeSurfaceService(converter_service=ConverterService())._resolve_graph_rag(
        collection.pk, {"graph_basic_search_config": {}}
    )

    assert result.rag_embedder_extra_headers == EMBEDDER_HEADERS
    assert result.rag_llm_extra_headers == LLM_HEADERS


@pytest.mark.django_db
def test_realtime_naive_rag_resolution_carries_embedder_headers_only(org, collection):
    _naive_rag(org, collection)

    result = RealtimeSurfaceService(converter_service=ConverterService())._resolve_naive_rag(
        collection.pk, {"search_limit": 5, "similarity_threshold": 0.5}
    )

    assert result.rag_embedder_extra_headers == EMBEDDER_HEADERS
    assert result.rag_llm_extra_headers is None


# ---- ProcessRagIndexingView: Django resolves the markers before calling knowledge_new ----


@pytest.fixture
def indexing_client(client_as, admin_acme, acme):
    api_client = client_as(admin_acme)
    api_client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
    return api_client


@pytest.fixture
def knowledge_client(monkeypatch):
    """Replace the HTTP client to knowledge_new; records what the view sends."""
    client = MagicMock()
    client.__enter__.return_value = client
    monkeypatch.setattr("tables.views.views.KnowledgeClient", lambda: client)
    return client


@pytest.mark.django_db
def test_indexing_sends_resolved_graph_rag_headers(indexing_client, knowledge_client, acme):
    secret_service.create(text="emb-plain", org=acme, name="EMB_GATEWAY")
    secret_service.create(text="llm-plain", org=acme, name="LLM_GATEWAY")
    collection = SourceCollection.objects.create(collection_name="Index KB", org=acme)
    graph_rag = _graph_rag(acme, collection)
    graph_rag.index_config = _index_config()
    graph_rag.save(update_fields=["index_config"])
    _link_document(graph_rag, collection)

    response = indexing_client.post(
        "/api/process-rag-indexing/",
        {"rag_id": graph_rag.graph_rag_id, "rag_type": "graph", "document_config_ids": [1]},
        format="json",
    )

    assert response.status_code == 202, response.data
    sent = knowledge_client.index.call_args.kwargs
    assert sent["embedding_extra_headers"] == {"X-Emb-Key": "emb-plain", "X-Trace": "t"}
    assert sent["llm_extra_headers"] == {"Authorization": "Bearer llm-plain"}
    # The stored configs keep their markers.
    graph_rag.embedder.refresh_from_db()
    assert graph_rag.embedder.extra_headers == EMBEDDER_HEADERS


@pytest.mark.django_db
def test_indexing_sends_resolved_naive_rag_headers(indexing_client, knowledge_client, acme):
    secret_service.create(text="emb-plain", org=acme, name="EMB_GATEWAY")
    collection = SourceCollection.objects.create(collection_name="Naive KB", org=acme)
    naive_rag = _naive_rag(acme, collection)
    DocumentMetadata.objects.create(source_collection=collection, file_name="a.txt")

    response = indexing_client.post(
        "/api/process-rag-indexing/",
        {"rag_id": naive_rag.naive_rag_id, "rag_type": "naive", "document_config_ids": [1]},
        format="json",
    )

    assert response.status_code == 202, response.data
    sent = knowledge_client.index.call_args.kwargs
    assert sent["embedding_extra_headers"] == {"X-Emb-Key": "emb-plain", "X-Trace": "t"}
    assert sent["llm_extra_headers"] is None


@pytest.mark.django_db
def test_indexing_refuses_a_marker_naming_another_orgs_secret(
    indexing_client, knowledge_client, acme, beta
):
    secret_service.create(text="beta-plain", org=beta, name="EMB_GATEWAY")
    collection = SourceCollection.objects.create(collection_name="Foreign KB", org=acme)
    naive_rag = _naive_rag(acme, collection)
    DocumentMetadata.objects.create(source_collection=collection, file_name="a.txt")

    response = indexing_client.post(
        "/api/process-rag-indexing/",
        {"rag_id": naive_rag.naive_rag_id, "rag_type": "naive", "document_config_ids": [1]},
        format="json",
    )

    # SecretResolutionError is a 500 today, the same as an unresolvable api key.
    assert response.status_code == 500
    assert response.data["code"] == "secret_resolution_error"
    assert "beta-plain" not in str(response.data)
    knowledge_client.index.assert_not_called()


def _index_config():
    return GraphRagIndexConfig.objects.create()


def _link_document(graph_rag, collection):
    document = DocumentMetadata.objects.create(source_collection=collection, file_name="a.txt")
    GraphRagDocument.objects.create(graph_rag=graph_rag, document=document)
