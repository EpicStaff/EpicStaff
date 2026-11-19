"""Error contract of the naive and graph `suggest-search-params` endpoints.

The frontend branches on `code` in the standard `{status_code, code, message}`
envelope, so each failure the user can fix has its own code. Only the knowledge
service client is replaced; the database, views and exception handler run for real.
"""

from unittest.mock import patch

import pytest
from django.urls import reverse
from loguru import logger
from rest_framework import status

from tables.clients.errors import ClientBadGatewayError
from tables.models import LLMConfig, LLMModel, Provider
from tables.models.knowledge_models import BaseRagType, GraphRag, SourceCollection
from tests.rbac_cross_org_fixtures import beta  # noqa: F401

pytestmark = pytest.mark.django_db

NAIVE_URL = reverse("naive-rag-suggest-search-params")
GRAPH_URL = reverse("graph-rag-suggest-search-params")
KNOWLEDGE_CLIENT_PATH = (
    "tables.services.knowledge_services.collection_management_service.KnowledgeClient"
)


@pytest.fixture
def knowledge_client():
    with patch(KNOWLEDGE_CLIENT_PATH) as client_class:
        yield client_class.return_value.__enter__.return_value


@pytest.fixture
def warnings_logged():
    """WARNING records logged through loguru during the test (caplog does not see loguru)."""
    records: list[dict] = []
    handler_id = logger.add(lambda message: records.append(message.record), level="WARNING")
    yield records
    logger.remove(handler_id)


@pytest.fixture
def llm_config(default_org):
    provider, _ = Provider.objects.get_or_create(name="openai")
    model, _ = LLMModel.objects.get_or_create(
        name="gpt-4o", defaults={"llm_provider": provider}
    )
    yield LLMConfig.objects.create(custom_name="graph-llm", model=model, org=default_org)


def _create_graph_rag(org, llm, rag_status) -> SourceCollection:
    collection = SourceCollection.objects.create(collection_name="Graph", org=org)
    base_rag_type = BaseRagType.objects.create(
        source_collection=collection, rag_type=BaseRagType.RagType.GRAPH
    )
    GraphRag.objects.create(base_rag_type=base_rag_type, llm=llm, rag_status=rag_status)
    return collection


def _post_graph(auth_client, collection):
    return auth_client.post(
        GRAPH_URL,
        {"knowledge_collection_id": collection.collection_id, "search_method": "basic"},
        format="json",
    )


def test_naive_rag_not_indexed_returns_index_not_ready_envelope(
    auth_client, source_collection, naive_rag
):
    response = auth_client.post(
        NAIVE_URL, {"knowledge_collection_id": source_collection.collection_id}, format="json"
    )

    assert response.status_code == status.HTTP_409_CONFLICT
    assert response.json() == {
        "status_code": 409,
        "code": "rag_index_not_ready",
        "message": (
            f"NaiveRAG index for collection {source_collection.collection_id} not ready. "
            "Run indexing and wait for rag_status='completed'."
        ),
    }


def test_graph_rag_not_indexed_returns_index_not_ready(
    auth_client, default_org, llm_config, knowledge_client
):
    collection = _create_graph_rag(
        default_org, llm_config, GraphRag.GraphRagStatus.PROCESSING
    )

    response = _post_graph(auth_client, collection)

    assert response.status_code == status.HTTP_409_CONFLICT
    body = response.json()
    assert body["code"] == "rag_index_not_ready"
    assert "error" not in body
    knowledge_client.metrics.assert_not_called()


def test_graph_rag_whose_llm_config_was_deleted_returns_llm_not_configured(
    auth_client, default_org, llm_config, knowledge_client
):
    collection = _create_graph_rag(
        default_org, llm_config, GraphRag.GraphRagStatus.COMPLETED
    )
    llm_config.delete()

    response = _post_graph(auth_client, collection)

    assert response.status_code == status.HTTP_409_CONFLICT
    assert response.json() == {
        "status_code": 409,
        "code": "graph_rag_llm_not_configured",
        "message": f"GraphRag for collection {collection.collection_id} has no LLM config.",
    }
    knowledge_client.metrics.assert_not_called()


def test_graph_rag_without_llm_reports_llm_before_index_status(
    auth_client, default_org, knowledge_client
):
    collection = _create_graph_rag(default_org, None, GraphRag.GraphRagStatus.NEW)

    response = _post_graph(auth_client, collection)

    assert response.status_code == status.HTTP_409_CONFLICT
    assert response.json()["code"] == "graph_rag_llm_not_configured"


def test_graph_rag_metrics_unavailable_keeps_retryable_rag_error(
    auth_client, default_org, llm_config, knowledge_client, warnings_logged
):
    collection = _create_graph_rag(
        default_org, llm_config, GraphRag.GraphRagStatus.COMPLETED
    )
    knowledge_client.metrics.side_effect = ClientBadGatewayError("upstream 500")

    response = _post_graph(auth_client, collection)

    assert response.status_code == status.HTTP_409_CONFLICT
    assert response.json() == {
        "status_code": 409,
        "code": "rag_error",
        "message": (
            f"GraphRAG metrics for collection {collection.collection_id} are temporarily "
            "unavailable. Retry shortly."
        ),
    }
    assert any(
        record["level"].name == "WARNING"
        and record["extra"].get("collection_id") == collection.collection_id
        and "upstream 500" in record["message"]
        for record in warnings_logged
    )


def test_graph_rag_ready_with_llm_returns_suggested_params(
    auth_client, default_org, llm_config, knowledge_client
):
    collection = _create_graph_rag(
        default_org, llm_config, GraphRag.GraphRagStatus.COMPLETED
    )
    knowledge_client.metrics.return_value = {"total_chunks": 50, "avg_chunk_size": 300.0}

    response = _post_graph(auth_client, collection)

    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert body["metrics"] == {
        "total_documents": 0,
        "total_chunks": 50,
        "avg_chunk_size": 300.0,
    }
    assert body["resolved_llm_name"] == "gpt-4o"
    assert body["suggested_params"] == {
        "search_method": "basic",
        "prompt": None,
        "k": 5,
        "max_context_tokens": body["safe_token_budget"],
    }


def test_graph_rag_in_another_org_returns_404_without_revealing_llm_state(
    auth_client, beta, knowledge_client  # noqa: F811
):
    collection = _create_graph_rag(beta, None, GraphRag.GraphRagStatus.COMPLETED)

    response = _post_graph(auth_client, collection)

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json()["code"] == "not_found"
    knowledge_client.metrics.assert_not_called()


@pytest.mark.parametrize(
    ("url", "extra_body", "expected_code"),
    [
        (NAIVE_URL, {}, "naive_rag_not_found"),
        (GRAPH_URL, {"search_method": "basic"}, "graph_rag_not_found"),
    ],
)
def test_collection_without_rag_returns_rag_not_found(
    auth_client, source_collection, url, extra_body, expected_code
):
    response = auth_client.post(
        url,
        {"knowledge_collection_id": source_collection.collection_id, **extra_body},
        format="json",
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json()["code"] == expected_code
