import httpx
import pytest

from tables.models import SourceCollection
from tables.models.knowledge_models import BaseRagType, GraphRag, GraphRagIndexConfig, NaiveRag
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

URL = "/api/process-rag-indexing/estimate/"

ESTIMATE = {
    "rag_type": "naive",
    "document_count": 2,
    "chunk_count": 5,
    "embedding": {"tokens": 1200, "exact": True, "cost_usd": 2.4e-05},
    "llm": None,
}


@pytest.fixture
def acme_client(client_as, acme):
    def _make(user):
        client = client_as(user)
        client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
        return client

    return _make


@pytest.fixture
def knowledge_calls(monkeypatch):
    """Replace only the HTTP call to knowledge_new; record what Django sent."""
    calls = []

    def fake_request(self, method, url, **kwargs):
        # litellm fetches its remote price map on first import; keep it offline and out of the record.
        if str(url).startswith("http"):
            return httpx.Response(503, request=httpx.Request(method, str(url)))
        calls.append({"method": method, "url": str(url), "json": kwargs.get("json")})
        return httpx.Response(200, json=ESTIMATE, request=httpx.Request(method, str(url)))

    monkeypatch.setattr(httpx.Client, "request", fake_request)
    return calls


def _rag(org, rag_type):
    collection = SourceCollection.objects.create(collection_name="estimate", org=org)
    base = BaseRagType.objects.create(rag_type=rag_type, source_collection=collection)
    if rag_type == BaseRagType.RagType.NAIVE:
        return NaiveRag.objects.create(base_rag_type=base).naive_rag_id
    return GraphRag.objects.create(base_rag_type=base).graph_rag_id


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("rag_type", "rag_kind"),
    [("naive", BaseRagType.RagType.NAIVE), ("graph", BaseRagType.RagType.GRAPH)],
)
def test_estimate_forwards_to_knowledge_and_returns_response_unchanged(
    acme_client, admin_acme, acme, knowledge_calls, rag_type, rag_kind
):
    rag_id = _rag(acme, rag_kind)

    response = acme_client(admin_acme).post(
        URL,
        {"rag_id": rag_id, "rag_type": rag_type, "document_config_ids": [3, 4]},
        format="json",
    )

    assert response.status_code == 200
    assert response.json() == ESTIMATE
    assert len(knowledge_calls) == 1
    assert knowledge_calls[0]["method"] == "post"
    assert knowledge_calls[0]["url"] == f"rags/{rag_type}/{rag_id}/index-estimate/"
    assert sorted(knowledge_calls[0]["json"]["document_ids"]) == [3, 4]


@pytest.mark.django_db
def test_estimate_of_another_orgs_rag_is_404(acme_client, admin_acme, beta, knowledge_calls):
    rag_id = _rag(beta, BaseRagType.RagType.NAIVE)

    response = acme_client(admin_acme).post(
        URL,
        {"rag_id": rag_id, "rag_type": "naive", "document_config_ids": [1]},
        format="json",
    )

    assert response.status_code == 404
    assert knowledge_calls == []


@pytest.mark.django_db
def test_estimate_denied_without_update_permission(
    acme_client, member_only, acme, knowledge_calls
):
    rag_id = _rag(acme, BaseRagType.RagType.NAIVE)

    response = acme_client(member_only).post(
        URL,
        {"rag_id": rag_id, "rag_type": "naive", "document_config_ids": [1]},
        format="json",
    )

    assert response.status_code == 403
    assert knowledge_calls == []


@pytest.mark.django_db
def test_estimate_rejects_invalid_body(acme_client, admin_acme, knowledge_calls):
    response = acme_client(admin_acme).post(URL, {"rag_type": "naive"}, format="json")

    assert response.status_code == 400
    assert knowledge_calls == []


@pytest.mark.django_db
def test_estimate_surfaces_knowledge_service_errors(
    acme_client, admin_acme, acme, monkeypatch
):
    rag_id = _rag(acme, BaseRagType.RagType.NAIVE)

    def failing_request(self, method, url, **kwargs):
        return httpx.Response(
            404, text="rag not found", request=httpx.Request(method, str(url))
        )

    monkeypatch.setattr(httpx.Client, "request", failing_request)

    response = acme_client(admin_acme).post(
        URL,
        {"rag_id": rag_id, "rag_type": "naive", "document_config_ids": [1]},
        format="json",
    )

    assert response.status_code == 404


GRAPH_INDEX_CONFIG = {"chunk_size": 400, "chunk_overlap": 50, "max_gleanings": 2}


@pytest.mark.django_db
def test_graph_estimate_forwards_unsaved_index_config(
    acme_client, admin_acme, acme, knowledge_calls
):
    rag_id = _rag(acme, BaseRagType.RagType.GRAPH)

    response = acme_client(admin_acme).post(
        URL,
        {
            "rag_id": rag_id,
            "rag_type": "graph",
            "document_config_ids": [3],
            "index_config": GRAPH_INDEX_CONFIG,
        },
        format="json",
    )

    assert response.status_code == 200
    assert knowledge_calls[0]["json"]["index_config"] == GRAPH_INDEX_CONFIG


@pytest.mark.django_db
def test_graph_estimate_without_index_config_sends_none(
    acme_client, admin_acme, acme, knowledge_calls
):
    rag_id = _rag(acme, BaseRagType.RagType.GRAPH)

    acme_client(admin_acme).post(
        URL,
        {"rag_id": rag_id, "rag_type": "graph", "document_config_ids": [3]},
        format="json",
    )

    assert "index_config" not in knowledge_calls[0]["json"]


@pytest.mark.django_db
def test_naive_estimate_ignores_index_config(acme_client, admin_acme, acme, knowledge_calls):
    rag_id = _rag(acme, BaseRagType.RagType.NAIVE)

    response = acme_client(admin_acme).post(
        URL,
        {
            "rag_id": rag_id,
            "rag_type": "naive",
            "document_config_ids": [3],
            "index_config": GRAPH_INDEX_CONFIG,
        },
        format="json",
    )

    assert response.status_code == 200
    assert "index_config" not in knowledge_calls[0]["json"]


@pytest.mark.django_db
@pytest.mark.parametrize(
    "index_config",
    [
        {"unknown_setting": 1},
        {"chunk_size": 1},
        {"max_gleanings": 9999},
        {"chunk_size": 200, "chunk_overlap": 300},
        {"chunk_strategy": "nonsense"},
        {"entity_types": []},
    ],
    ids=["unknown-key", "chunk-size-too-small", "gleanings-too-big", "overlap", "strategy", "empty-entities"],
)
def test_graph_estimate_rejects_invalid_index_config(
    acme_client, admin_acme, acme, knowledge_calls, index_config
):
    rag_id = _rag(acme, BaseRagType.RagType.GRAPH)

    response = acme_client(admin_acme).post(
        URL,
        {
            "rag_id": rag_id,
            "rag_type": "graph",
            "document_config_ids": [3],
            "index_config": index_config,
        },
        format="json",
    )

    assert response.status_code == 400
    assert "index_config" in response.json()
    assert knowledge_calls == []


@pytest.mark.django_db
def test_graph_estimate_never_saves_index_config(acme_client, admin_acme, acme, knowledge_calls):
    rag_id = _rag(acme, BaseRagType.RagType.GRAPH)
    stored = GraphRag.objects.get(pk=rag_id).index_config

    acme_client(admin_acme).post(
        URL,
        {
            "rag_id": rag_id,
            "rag_type": "graph",
            "document_config_ids": [3],
            "index_config": GRAPH_INDEX_CONFIG,
        },
        format="json",
    )

    assert GraphRag.objects.get(pk=rag_id).index_config == stored


FULL_FORM_INDEX_CONFIG = {
    "file_type": "text",
    "chunk_size": 400,
    "chunk_overlap": 50,
    "chunk_strategy": "tokens",
    "entity_types": ["person", "place"],
    "max_gleanings": 2,
    "max_cluster_size": 10,
}


@pytest.mark.django_db
def test_graph_estimate_forwards_only_estimate_relevant_keys_of_full_form(
    acme_client, admin_acme, acme, knowledge_calls
):
    rag_id = _rag(acme, BaseRagType.RagType.GRAPH)

    response = acme_client(admin_acme).post(
        URL,
        {
            "rag_id": rag_id,
            "rag_type": "graph",
            "document_config_ids": [3],
            "index_config": FULL_FORM_INDEX_CONFIG,
        },
        format="json",
    )

    assert response.status_code == 200
    assert knowledge_calls[0]["json"]["index_config"] == {
        "chunk_size": 400,
        "chunk_overlap": 50,
        "max_gleanings": 2,
    }


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("stored", "index_config"),
    [
        ({"chunk_size": 300, "chunk_overlap": 100}, {"chunk_overlap": 900}),
        ({"chunk_size": 300, "chunk_overlap": 100}, {"chunk_size": 100}),
    ],
    ids=["overlap-vs-stored-size", "size-vs-stored-overlap"],
)
def test_graph_estimate_rejects_partial_override_conflicting_with_stored_config(
    acme_client, admin_acme, acme, knowledge_calls, stored, index_config
):
    rag_id = _rag(acme, BaseRagType.RagType.GRAPH)
    stored_config = GraphRagIndexConfig.objects.create(**stored)
    GraphRag.objects.filter(pk=rag_id).update(index_config=stored_config)

    response = acme_client(admin_acme).post(
        URL,
        {
            "rag_id": rag_id,
            "rag_type": "graph",
            "document_config_ids": [3],
            "index_config": index_config,
        },
        format="json",
    )

    assert response.status_code == 400
    assert response.json() == {
        "index_config": {"chunk_overlap": ["'chunk_overlap' must be less than 'chunk_size'"]}
    }
    assert knowledge_calls == []
