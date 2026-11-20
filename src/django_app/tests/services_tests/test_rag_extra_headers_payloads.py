"""RAG embedder/LLM extra headers and connections travel next to the RAG api keys on every path.

The payloads carry the raw headers and connections, `epicstaff_secret(<name>)` markers
included; SecretResolver fills them only on the published copy, so any persisted copy
keeps the markers. Connections go out under the LiteLLM argument each field is sent as.
"""

from unittest.mock import MagicMock

import pytest

from rbac.models import Organization
from ai_models.models import EmbeddingConfig, EmbeddingModel, LLMConfig, LLMModel, Provider
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
from tables.exceptions import ConfigNeedsReviewError
from tables.services.converter_service import ConverterService, NodeRagCredentials
from tables.services.realtime_surface_service import RealtimeSurfaceService
from tables.services.secrets import secret_resolver, secret_service
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403
from tests.sealed_values import open_sealed, open_sealed_headers

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
    model = EmbeddingModel.objects.create(name="emb-model", org=org, embedding_provider=provider)
    return EmbeddingConfig.objects.create(
        custom_name="emb-cfg",
        model=model,
        org=org,
        extra_headers=extra_headers or {},
        connection={"base_url": "http://gateway:8080/v1"},
        parameters={"dimensions": 256},
    )


LLM_CONNECTION = {
    "aws_access_key_id": "epicstaff_secret(AWS_KEY_ID)",
    "aws_region_name": "eu-west-1",
}
# The bedrock catalog entry sends each of these fields under its own name.
LLM_CONNECTION_ARGUMENTS = LLM_CONNECTION


def _llm(org, extra_headers=None):
    provider, _ = Provider.objects.get_or_create(name="bedrock")
    model = LLMModel.objects.create(name="llm-model", org=org, llm_provider=provider)
    return LLMConfig.objects.create(
        custom_name="llm-cfg",
        model=model,
        org=org,
        extra_headers=extra_headers or {},
        connection=LLM_CONNECTION,
        parameters={"max_tokens": 512},
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
    assert embedder.config.connection == {"api_base": "http://gateway:8080/v1"}


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
    assert data.embedder_connection == {"api_base": "http://gateway:8080/v1"}
    assert data.llm_connection == LLM_CONNECTION_ARGUMENTS
    # knowledge_new sends the settings as it gets them.
    assert data.embedder_parameters == {"dimensions": 256}
    assert data.llm_parameters == {"max_tokens": 512}
    # The dump is what gets persisted: markers, never plaintext.
    dumped = data.model_dump()
    assert dumped["embedder_extra_headers"] == EMBEDDER_HEADERS
    assert dumped["llm_extra_headers"] == LLM_HEADERS
    assert dumped["llm_connection"] == LLM_CONNECTION_ARGUMENTS


@pytest.mark.django_db
def test_published_knowledge_node_resolves_connection_markers_of_its_org(org, collection):
    secret_service.create(text="AKIA-plain", org=org, name="AWS_KEY_ID")
    secret_service.create(text="emb-plain", org=org, name="EMB_GATEWAY")
    secret_service.create(text="llm-plain", org=org, name="LLM_GATEWAY")
    graph_rag = _graph_rag(org, collection)
    node = KnowledgeNode.objects.create(
        graph=Graph.objects.create(org=org, name="resolved-flow"),
        source_collection=collection,
        rag_type="graph",
        rag_id=graph_rag.graph_rag_id,
        query="q",
    )
    data = ConverterService().convert_knowledge_node_to_pydantic(
        node, resolver=lambda node_id: "knowledge"
    )

    published = secret_resolver.resolve_payload(payload=data, org_id=org.id)

    assert "AKIA-plain" not in str(published.llm_connection)
    assert open_sealed_headers(published.llm_connection) == {
        "aws_access_key_id": "AKIA-plain",
        "aws_region_name": "eu-west-1",
    }
    assert data.llm_connection == LLM_CONNECTION_ARGUMENTS


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
    assert data.embedder_connection == {"api_base": "http://gateway:8080/v1"}
    assert data.llm_connection is None
    assert data.embedder_parameters == {"dimensions": 256}
    assert data.llm_parameters is None


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

    # One query for the RAG, then for the embedder and the LLM each: the config, its model
    # and the model's provider, which names the connection's LiteLLM arguments.
    with django_assert_num_queries(7):
        credentials = ConverterService._node_rag_credentials(node)

    assert credentials.embedder_api_key_secret_id == secret.pk
    assert credentials.llm_api_key_secret_id is None
    assert credentials.embedder_extra_headers == EMBEDDER_HEADERS
    assert credentials.llm_extra_headers == LLM_HEADERS
    assert credentials.embedder_connection == {"api_base": "http://gateway:8080/v1"}
    assert credentials.llm_connection == LLM_CONNECTION_ARGUMENTS
    assert credentials.embedder_parameters == {"dimensions": 256}
    assert credentials.llm_parameters == {"max_tokens": 512}


@pytest.mark.django_db
def test_node_without_rag_has_empty_credentials_and_issues_no_query(
    org, django_assert_num_queries
):
    node = KnowledgeNode.objects.create(
        graph=Graph.objects.create(org=org, name="no-rag-once-flow"), query="q"
    )

    with django_assert_num_queries(0):
        credentials = ConverterService._node_rag_credentials(node)

    assert credentials == NodeRagCredentials()


@pytest.mark.django_db
def test_realtime_graph_rag_resolution_carries_headers(org, collection):
    _graph_rag(org, collection)

    result = RealtimeSurfaceService(converter_service=ConverterService())._resolve_graph_rag(
        collection.pk, {"graph_basic_search_config": {}}
    )

    assert result.rag_embedder_extra_headers == EMBEDDER_HEADERS
    assert result.rag_llm_extra_headers == LLM_HEADERS
    assert result.rag_embedder_connection == {"api_base": "http://gateway:8080/v1"}
    assert result.rag_llm_connection == LLM_CONNECTION_ARGUMENTS
    assert result.rag_embedder_parameters == {"dimensions": 256}
    assert result.rag_llm_parameters == {"max_tokens": 512}


@pytest.mark.django_db
def test_realtime_naive_rag_resolution_carries_embedder_headers_only(org, collection):
    _naive_rag(org, collection)

    result = RealtimeSurfaceService(converter_service=ConverterService())._resolve_naive_rag(
        collection.pk, {"search_limit": 5, "similarity_threshold": 0.5}
    )

    assert result.rag_embedder_extra_headers == EMBEDDER_HEADERS
    assert result.rag_llm_extra_headers is None
    assert result.rag_embedder_connection == {"api_base": "http://gateway:8080/v1"}
    assert result.rag_llm_connection is None
    assert result.rag_embedder_parameters == {"dimensions": 256}
    assert result.rag_llm_parameters is None


# ---- ProcessRagIndexingView: Django seals the markers before calling knowledge_new ----


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
    secret_service.create(text="AKIA-plain", org=acme, name="AWS_KEY_ID")
    collection = SourceCollection.objects.create(collection_name="Index KB", org=acme)
    graph_rag = _graph_rag(acme, collection)
    graph_rag.index_config = _index_config()
    graph_rag.save(update_fields=["index_config"])
    _link_document(graph_rag, collection)
    graph_rag.embedder.api_key_secret = secret_service.create(
        text="emb-key-plain", org=acme, name="EMB_API_KEY"
    )
    graph_rag.embedder.save(update_fields=["api_key_secret"])
    graph_rag.llm.api_key_secret = secret_service.create(
        text="llm-key-plain", org=acme, name="LLM_API_KEY"
    )
    graph_rag.llm.save(update_fields=["api_key_secret"])

    response = indexing_client.post(
        "/api/process-rag-indexing/",
        {"rag_id": graph_rag.graph_rag_id, "rag_type": "graph", "document_config_ids": [1]},
        format="json",
    )

    assert response.status_code == 202, response.data
    sent = knowledge_client.index.call_args.kwargs
    assert open_sealed(sent["embedding_api_key"]) == "emb-key-plain"
    assert open_sealed(sent["llm_api_key"]) == "llm-key-plain"
    assert "emb-plain" not in str(sent["embedding_extra_headers"])
    assert "llm-plain" not in str(sent["llm_extra_headers"])
    assert open_sealed_headers(sent["embedding_extra_headers"]) == {
        "X-Emb-Key": "emb-plain",
        "X-Trace": "t",
    }
    assert open_sealed_headers(sent["llm_extra_headers"]) == {"Authorization": "Bearer llm-plain"}
    assert sent["embedding_connection"] == {"api_base": "http://gateway:8080/v1"}
    assert "AKIA-plain" not in str(sent["llm_connection"])
    assert open_sealed_headers(sent["llm_connection"]) == {
        "aws_access_key_id": "AKIA-plain",
        "aws_region_name": "eu-west-1",
    }
    assert sent["embedding_parameters"] == {"dimensions": 256}
    assert sent["llm_parameters"] == {"max_tokens": 512}
    # The stored configs keep their markers.
    graph_rag.embedder.refresh_from_db()
    assert graph_rag.embedder.extra_headers == EMBEDDER_HEADERS
    graph_rag.llm.refresh_from_db()
    assert graph_rag.llm.connection == LLM_CONNECTION


@pytest.mark.django_db
def test_indexing_sends_resolved_naive_rag_headers(indexing_client, knowledge_client, acme):
    secret_service.create(text="emb-plain", org=acme, name="EMB_GATEWAY")
    collection = SourceCollection.objects.create(collection_name="Naive KB", org=acme)
    naive_rag = _naive_rag(acme, collection)
    DocumentMetadata.objects.create(source_collection=collection, file_name="a.txt")
    naive_rag.embedder.api_key_secret = secret_service.create(
        text="emb-key-plain", org=acme, name="EMB_API_KEY"
    )
    naive_rag.embedder.save(update_fields=["api_key_secret"])

    response = indexing_client.post(
        "/api/process-rag-indexing/",
        {"rag_id": naive_rag.naive_rag_id, "rag_type": "naive", "document_config_ids": [1]},
        format="json",
    )

    assert response.status_code == 202, response.data
    sent = knowledge_client.index.call_args.kwargs
    assert open_sealed(sent["embedding_api_key"]) == "emb-key-plain"
    assert sent["llm_api_key"] is None
    assert open_sealed_headers(sent["embedding_extra_headers"]) == {
        "X-Emb-Key": "emb-plain",
        "X-Trace": "t",
    }
    assert sent["llm_extra_headers"] is None
    assert sent["embedding_connection"] == {"api_base": "http://gateway:8080/v1"}
    assert sent["llm_connection"] is None
    assert sent["embedding_parameters"] == {"dimensions": 256}
    assert sent["llm_parameters"] is None


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


@pytest.mark.django_db
def test_indexing_resolves_a_connection_marker_only_from_the_rag_s_own_org(
    indexing_client, knowledge_client, acme, beta
):
    secret_service.create(text="emb-plain", org=acme, name="EMB_GATEWAY")
    secret_service.create(text="llm-plain", org=acme, name="LLM_GATEWAY")
    # Only beta has the secret the LLM connection's marker names.
    secret_service.create(text="beta-akia", org=beta, name="AWS_KEY_ID")
    collection = SourceCollection.objects.create(collection_name="Foreign conn KB", org=acme)
    graph_rag = _graph_rag(acme, collection)
    graph_rag.index_config = _index_config()
    graph_rag.save(update_fields=["index_config"])
    _link_document(graph_rag, collection)

    response = indexing_client.post(
        "/api/process-rag-indexing/",
        {"rag_id": graph_rag.graph_rag_id, "rag_type": "graph", "document_config_ids": [1]},
        format="json",
    )

    assert response.status_code == 500
    assert response.data["code"] == "secret_resolution_error"
    assert "beta-akia" not in str(response.data)
    knowledge_client.index.assert_not_called()


def _index_config():
    return GraphRagIndexConfig.objects.create()


def _link_document(graph_rag, collection):
    document = DocumentMetadata.objects.create(source_collection=collection, file_name="a.txt")
    GraphRagDocument.objects.create(graph_rag=graph_rag, document=document)


# ---- A RAG config whose settings its model does not accept refuses every path ----


def _make_settings_stale(rag):
    """Store settings the models do not accept, as a catalog update leaves them."""
    rag.embedder.parameters = {"dimensions": 256, "task_type": "retrieval_document"}
    rag.embedder.save(update_fields=["parameters"])
    if getattr(rag, "llm", None) is not None:
        rag.llm.parameters = {"max_tokens": 512, "temperature": 0.1}
        rag.llm.save(update_fields=["parameters"])


@pytest.mark.django_db
def test_knowledge_node_refuses_an_embedder_the_model_does_not_accept(org, collection):
    graph_rag = _graph_rag(org, collection)
    _make_settings_stale(graph_rag)
    node = KnowledgeNode.objects.create(
        graph=Graph.objects.create(org=org, name="stale-flow"),
        source_collection=collection,
        rag_type="graph",
        rag_id=graph_rag.graph_rag_id,
        query="q",
    )

    with pytest.raises(ConfigNeedsReviewError) as refusal:
        ConverterService().convert_knowledge_node_to_pydantic(node, resolver=lambda node_id: "knowledge")

    assert str(refusal.value.detail).startswith("Embedding config 'emb-cfg' has settings its model does not accept: task_type")


@pytest.mark.django_db
def test_knowledge_node_refuses_a_graph_rag_llm_the_model_does_not_accept(org, collection):
    graph_rag = _graph_rag(org, collection)
    graph_rag.llm.parameters = {"max_tokens": 512, "temperature": 0.1}
    graph_rag.llm.save(update_fields=["parameters"])
    node = KnowledgeNode.objects.create(
        graph=Graph.objects.create(org=org, name="stale-llm-flow"),
        source_collection=collection,
        rag_type="graph",
        rag_id=graph_rag.graph_rag_id,
        query="q",
    )

    with pytest.raises(ConfigNeedsReviewError) as refusal:
        ConverterService().convert_knowledge_node_to_pydantic(node, resolver=lambda node_id: "knowledge")

    assert str(refusal.value.detail).startswith("LLM config 'llm-cfg' has settings its model does not accept: temperature")


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("build_rag", "resolve"),
    [
        (_naive_rag, lambda service, collection_id: service._resolve_naive_rag(
            collection_id, {"search_limit": 5, "similarity_threshold": 0.5}
        )),
        (_graph_rag, lambda service, collection_id: service._resolve_graph_rag(
            collection_id, {"graph_basic_search_config": {}}
        )),
    ],
    ids=["naive", "graph"],
)
def test_realtime_rag_resolution_refuses_settings_the_model_does_not_accept(org, collection, build_rag, resolve):
    _make_settings_stale(build_rag(org, collection))

    with pytest.raises(ConfigNeedsReviewError):
        resolve(RealtimeSurfaceService(converter_service=ConverterService()), collection.pk)


@pytest.mark.django_db
def test_indexing_refuses_a_naive_rag_embedder_the_model_does_not_accept(indexing_client, knowledge_client, acme):
    collection = SourceCollection.objects.create(collection_name="Stale naive KB", org=acme)
    naive_rag = _naive_rag(acme, collection)
    _make_settings_stale(naive_rag)
    DocumentMetadata.objects.create(source_collection=collection, file_name="a.txt")

    response = indexing_client.post(
        "/api/process-rag-indexing/",
        {"rag_id": naive_rag.naive_rag_id, "rag_type": "naive", "document_config_ids": [1]},
        format="json",
    )

    assert response.status_code == 400
    assert response.data["code"] == "config_needs_review"
    assert response.data["message"].startswith(
        "Embedding config 'emb-cfg' has settings its model does not accept: task_type"
    )
    knowledge_client.index.assert_not_called()


@pytest.mark.django_db
def test_indexing_refuses_a_graph_rag_llm_the_model_does_not_accept(indexing_client, knowledge_client, acme):
    collection = SourceCollection.objects.create(collection_name="Stale graph KB", org=acme)
    graph_rag = _graph_rag(acme, collection)
    graph_rag.index_config = _index_config()
    graph_rag.save(update_fields=["index_config"])
    _link_document(graph_rag, collection)
    graph_rag.llm.parameters = {"max_tokens": 512, "temperature": 0.1}
    graph_rag.llm.save(update_fields=["parameters"])

    response = indexing_client.post(
        "/api/process-rag-indexing/",
        {"rag_id": graph_rag.graph_rag_id, "rag_type": "graph", "document_config_ids": [1]},
        format="json",
    )

    assert response.status_code == 400
    assert response.data["code"] == "config_needs_review"
    assert "LLM config 'llm-cfg'" in response.data["message"]
    knowledge_client.index.assert_not_called()
