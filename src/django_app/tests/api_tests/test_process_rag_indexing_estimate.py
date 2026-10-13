import httpx
import pytest

from tables.models import SourceCollection
from tables.models.knowledge_models import BaseRagType, GraphRag, NaiveRag
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
