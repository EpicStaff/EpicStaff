import httpx
import pytest

from tables.models import SourceCollection
from tables.models.knowledge_models import (
    BaseRagType,
    DocumentContent,
    DocumentMetadata,
    GraphRag,
    NaiveRag,
    NaiveRagDocumentConfig,
)
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

URL = "/api/process-rag-indexing/estimate/"

ESTIMATE = {
    "rag_type": "naive",
    "document_count": 2,
    "chunk_count": 5,
    "embedding": {"tokens": 1200, "exact": True, "cost_usd": 2.4e-05},
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
def test_naive_estimate_forwards_to_knowledge_and_returns_response_unchanged(
    acme_client, admin_acme, acme, knowledge_calls
):
    rag_id = _rag(acme, BaseRagType.RagType.NAIVE)
    rag_type = "naive"

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


@pytest.mark.django_db
def test_graph_estimate_is_rejected_without_calling_knowledge(
    acme_client, admin_acme, acme, knowledge_calls
):
    rag_id = _rag(acme, BaseRagType.RagType.GRAPH)

    response = acme_client(admin_acme).post(
        URL,
        {"rag_id": rag_id, "rag_type": "graph", "document_config_ids": [1]},
        format="json",
    )

    assert response.status_code == 400
    assert response.json() == {"error": "Estimate is not available for GraphRAG."}
    assert knowledge_calls == []


@pytest.mark.django_db
def test_graph_estimate_of_another_orgs_rag_is_404(
    acme_client, admin_acme, beta, knowledge_calls
):
    rag_id = _rag(beta, BaseRagType.RagType.GRAPH)

    response = acme_client(admin_acme).post(
        URL,
        {"rag_id": rag_id, "rag_type": "graph", "document_config_ids": [1]},
        format="json",
    )

    assert response.status_code == 404
    assert knowledge_calls == []


@pytest.mark.django_db
def test_graph_estimate_denied_without_update_permission(
    acme_client, member_only, acme, knowledge_calls
):
    rag_id = _rag(acme, BaseRagType.RagType.GRAPH)

    response = acme_client(member_only).post(
        URL,
        {"rag_id": rag_id, "rag_type": "graph", "document_config_ids": [1]},
        format="json",
    )

    assert response.status_code == 403
    assert knowledge_calls == []


def _naive_rag_with_config(org, file_type="pdf", **config_fields):
    """A naive RAG in `org` with one stored config; returns (rag_id, config)."""
    rag_id = _rag(org, BaseRagType.RagType.NAIVE)
    rag = NaiveRag.objects.get(naive_rag_id=rag_id)
    document = DocumentMetadata.objects.create(
        source_collection=rag.base_rag_type.source_collection,
        document_content=DocumentContent.objects.create(content=b"text"),
        file_name=f"doc.{file_type}",
        file_type=file_type,
        file_size=4,
    )
    stored = {"chunk_strategy": "token", "chunk_size": 1000, "chunk_overlap": 150}
    config = NaiveRagDocumentConfig.objects.create(
        naive_rag=rag, document=document, **{**stored, **config_fields}
    )
    return rag_id, config


def _estimate_body(rag_id, config, **override_fields):
    body = {
        "rag_id": rag_id,
        "rag_type": "naive",
        "document_config_ids": [config.naive_rag_document_id],
    }
    if override_fields:
        body["document_configs"] = [
            {"document_config_id": config.naive_rag_document_id, **override_fields}
        ]
    return body


@pytest.mark.django_db
def test_estimate_forwards_the_override_merged_with_the_stored_config_and_saves_nothing(
    acme_client, admin_acme, acme, knowledge_calls
):
    rag_id, config = _naive_rag_with_config(acme, additional_params={"keep": 1})

    response = acme_client(admin_acme).post(
        URL, _estimate_body(rag_id, config, chunk_size=500), format="json"
    )

    assert response.status_code == 200
    assert knowledge_calls[0]["json"]["chunking_overrides"] == [
        {
            "document_id": config.naive_rag_document_id,
            "chunking_config": {
                "chunk_strategy": "token",
                "chunk_size": 500,
                "chunk_overlap": 150,
                "extra": {"keep": 1},
            },
        }
    ]
    config.refresh_from_db()
    assert (config.chunk_size, config.status) == (1000, "new")


@pytest.mark.django_db
def test_estimate_override_can_replace_strategy_and_additional_params(
    acme_client, admin_acme, acme, knowledge_calls
):
    rag_id, config = _naive_rag_with_config(acme)

    response = acme_client(admin_acme).post(
        URL,
        _estimate_body(
            rag_id, config, chunk_strategy="character", additional_params={"regex": "x"}
        ),
        format="json",
    )

    assert response.status_code == 200
    forwarded = knowledge_calls[0]["json"]["chunking_overrides"][0]["chunking_config"]
    assert forwarded == {
        "chunk_strategy": "character",
        "chunk_size": 1000,
        "chunk_overlap": 150,
        "extra": {"regex": "x"},
    }


@pytest.mark.django_db
def test_estimate_without_overrides_forwards_an_empty_override_list(acme_client, admin_acme, acme, knowledge_calls):
    rag_id, config = _naive_rag_with_config(acme)

    response = acme_client(admin_acme).post(URL, _estimate_body(rag_id, config), format="json")

    assert response.status_code == 200
    assert knowledge_calls[0]["json"]["chunking_overrides"] == []


@pytest.mark.django_db
def test_estimate_override_of_a_config_in_another_orgs_rag_is_404(
    acme_client, admin_acme, acme, beta, knowledge_calls
):
    rag_id, _ = _naive_rag_with_config(acme)
    _, foreign_config = _naive_rag_with_config(beta)

    response = acme_client(admin_acme).post(
        URL,
        {
            "rag_id": rag_id,
            "rag_type": "naive",
            "document_config_ids": [foreign_config.naive_rag_document_id],
            "document_configs": [
                {"document_config_id": foreign_config.naive_rag_document_id, "chunk_size": 500}
            ],
        },
        format="json",
    )

    assert response.status_code == 404
    assert knowledge_calls == []
    foreign_config.refresh_from_db()
    assert foreign_config.chunk_size == 1000


@pytest.mark.django_db
def test_estimate_override_for_a_missing_config_in_the_same_org_is_404(
    acme_client, admin_acme, acme, knowledge_calls
):
    rag_id, config = _naive_rag_with_config(acme)
    missing_id = config.naive_rag_document_id + 1000
    body = _estimate_body(rag_id, config)
    body["document_config_ids"] = [missing_id]
    body["document_configs"] = [{"document_config_id": missing_id, "chunk_size": 500}]

    response = acme_client(admin_acme).post(URL, body, format="json")

    assert response.status_code == 404
    assert str(missing_id) in response.json()["error"]
    assert knowledge_calls == []


@pytest.mark.django_db
def test_estimate_names_the_invalid_document_when_only_one_override_is_invalid(
    acme_client, admin_acme, acme, knowledge_calls
):
    rag_id, valid_config = _naive_rag_with_config(acme)
    rag = NaiveRag.objects.get(naive_rag_id=rag_id)
    invalid_config = NaiveRagDocumentConfig.objects.create(
        naive_rag=rag,
        document=DocumentMetadata.objects.create(
            source_collection=rag.base_rag_type.source_collection,
            document_content=DocumentContent.objects.create(content=b"text"),
            file_name="other.pdf",
            file_type="pdf",
            file_size=4,
        ),
        chunk_strategy="token",
        chunk_size=1000,
        chunk_overlap=150,
    )
    valid_id = valid_config.naive_rag_document_id
    invalid_id = invalid_config.naive_rag_document_id

    response = acme_client(admin_acme).post(
        URL,
        {
            "rag_id": rag_id,
            "rag_type": "naive",
            "document_config_ids": [valid_id, invalid_id],
            "document_configs": [
                {"document_config_id": valid_id, "chunk_size": 500},
                {"document_config_id": invalid_id, "chunk_size": 100},
            ],
        },
        format="json",
    )

    assert response.status_code == 400
    body = response.json()
    assert body["error"] == "'chunk_overlap' must be less than 'chunk_size'"
    assert [item["document_config_id"] for item in body["errors"]] == [invalid_id]
    assert body["errors"][0]["field"] == "chunk_overlap"
    assert knowledge_calls == []


@pytest.mark.django_db
def test_estimate_non_object_additional_params_override_is_400_naming_field_and_document(
    acme_client, admin_acme, acme, knowledge_calls
):
    rag_id, config = _naive_rag_with_config(acme)

    response = acme_client(admin_acme).post(
        URL, _estimate_body(rag_id, config, additional_params=[1, 2]), format="json"
    )

    assert response.status_code == 400
    body = response.json()
    assert body["error"] == "'additional_params' must be an object"
    assert body["errors"] == [
        {
            "document_config_id": config.naive_rag_document_id,
            "field": "additional_params",
            "value": [1, 2],
            "reason": "'additional_params' must be an object",
        }
    ]
    assert knowledge_calls == []


@pytest.mark.django_db
def test_estimate_override_breaking_overlap_rule_against_stored_value_is_400(
    acme_client, admin_acme, acme, knowledge_calls
):
    # Stored overlap is 150, so a size of 100 is only invalid once merged with it.
    rag_id, config = _naive_rag_with_config(acme)

    response = acme_client(admin_acme).post(
        URL, _estimate_body(rag_id, config, chunk_size=100), format="json"
    )

    assert response.status_code == 400
    assert response.json()["error"] == "'chunk_overlap' must be less than 'chunk_size'"
    assert knowledge_calls == []


@pytest.mark.django_db
def test_estimate_override_with_strategy_not_allowed_for_the_file_type_is_400(
    acme_client, admin_acme, acme, knowledge_calls
):
    rag_id, config = _naive_rag_with_config(acme, file_type="pdf")

    response = acme_client(admin_acme).post(
        URL, _estimate_body(rag_id, config, chunk_strategy="markdown"), format="json"
    )

    assert response.status_code == 400
    assert "chunk_strategy 'markdown' is not valid" in response.json()["error"]
    assert knowledge_calls == []


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("override_fields", "expected_message_part"),
    [
        ({"chunk_size": 19}, "chunk_size"),
        ({"chunk_size": 8001}, "chunk_size"),
        ({"chunk_overlap": -1}, "chunk_overlap"),
        ({"chunk_strategy": "nope"}, "chunk_strategy"),
        ({}, "At least one field must be provided"),
    ],
    ids=["size-below-min", "size-above-max", "overlap-negative", "unknown-strategy", "no-fields"],
)
def test_estimate_override_fields_are_validated_like_the_save_payload(
    acme_client, admin_acme, acme, knowledge_calls, override_fields, expected_message_part
):
    rag_id, config = _naive_rag_with_config(acme)
    body = _estimate_body(rag_id, config)
    body["document_configs"] = [
        {"document_config_id": config.naive_rag_document_id, **override_fields}
    ]

    response = acme_client(admin_acme).post(URL, body, format="json")

    assert response.status_code == 400
    assert expected_message_part in str(response.json())
    assert knowledge_calls == []


@pytest.mark.django_db
def test_estimate_rejects_override_for_a_config_outside_document_config_ids(
    acme_client, admin_acme, acme, knowledge_calls
):
    rag_id, config = _naive_rag_with_config(acme)
    body = _estimate_body(rag_id, config, chunk_size=500)
    body["document_config_ids"] = [config.naive_rag_document_id + 1]

    response = acme_client(admin_acme).post(URL, body, format="json")

    assert response.status_code == 400
    assert knowledge_calls == []


@pytest.mark.django_db
def test_estimate_rejects_duplicate_override_ids(acme_client, admin_acme, acme, knowledge_calls):
    rag_id, config = _naive_rag_with_config(acme)
    body = _estimate_body(rag_id, config, chunk_size=500)
    body["document_configs"] *= 2

    response = acme_client(admin_acme).post(URL, body, format="json")

    assert response.status_code == 400
    assert knowledge_calls == []


@pytest.mark.django_db
def test_graph_estimate_with_overrides_is_still_rejected(
    acme_client, admin_acme, acme, knowledge_calls
):
    rag_id = _rag(acme, BaseRagType.RagType.GRAPH)

    response = acme_client(admin_acme).post(
        URL,
        {
            "rag_id": rag_id,
            "rag_type": "graph",
            "document_config_ids": [1],
            "document_configs": [{"document_config_id": 1, "chunk_size": 500}],
        },
        format="json",
    )

    assert response.status_code == 400
    assert response.json() == {"error": "Estimate is not available for GraphRAG."}
    assert knowledge_calls == []
