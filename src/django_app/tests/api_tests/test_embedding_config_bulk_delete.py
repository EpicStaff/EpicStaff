"""API tests for EmbeddingConfigReadWriteViewSet bulk delete, via the mixin.

Two referencing buckets: PROJECTS (the deprecated Crew.embedding_config) and
KNOWLEDGE_SOURCES (GraphRag.embedder + NaiveRag.embedder, merged). Usage is read
from a `?dry_run=true` preview; a real delete returns it empty.
"""

import pytest

from tables.models import Crew, EmbeddingConfig
from tables.models.knowledge_models.collection_models import (
    BaseRagType,
    SourceCollection,
)
from tables.models.knowledge_models.graphrag_models import GraphRag
from tables.models.knowledge_models.naive_rag_models import NaiveRag
from tables.models.rbac_models import (
    Organization,
)
from tables.models.rbac_models.rbac_enums import Permission, ResourceType
from tests.api_tests.bulk_delete_helpers import custom_role_client, org_admin_client


@pytest.fixture
def org_a(db):
    return Organization.objects.create(name="Org A")


@pytest.fixture
def org_b(db):
    return Organization.objects.create(name="Org B")


def _config(org, name="cfg"):
    return EmbeddingConfig.objects.create(org=org, custom_name=name)


def by_type(usage, resource_type):
    return next(
        s for s in usage["by_resource_type"] if s["resource_type"] == resource_type
    )


def _preview_usage(client, config_id):
    resp = client.post(
        "/api/embedding-configs/bulk-delete/?dry_run=true",
        {"ids": [config_id]},
        format="json",
    )
    assert resp.data["dry_run"] is True, resp.data
    return resp.data["usage"][str(config_id)]


@pytest.mark.django_db
def test_bulk_delete_happy_path(django_user_model, org_a):
    client = org_admin_client(django_user_model, org_a, "admin@example.com")
    c1, c2 = _config(org_a, "c1"), _config(org_a, "c2")

    resp = client.post(
        "/api/embedding-configs/bulk-delete/", {"ids": [c1.id, c2.id]}, format="json"
    )

    assert resp.status_code == 200, resp.data
    assert sorted(resp.data["deleted_ids"]) == sorted([c1.id, c2.id])
    assert not EmbeddingConfig.objects.filter(id__in=[c1.id, c2.id]).exists()


@pytest.mark.django_db
def test_bulk_delete_cross_org_id_not_found(django_user_model, org_a, org_b):
    client = org_admin_client(django_user_model, org_a, "admin@example.com")
    other = _config(org_b, "other")

    resp = client.post(
        "/api/embedding-configs/bulk-delete/", {"ids": [other.id]}, format="json"
    )

    assert resp.status_code == 207, resp.data
    assert resp.data["not_found_ids"] == [other.id]


@pytest.mark.django_db
def test_bulk_delete_empty_ids_rejected(django_user_model, org_a):
    client = org_admin_client(django_user_model, org_a, "admin@example.com")

    resp = client.post(
        "/api/embedding-configs/bulk-delete/", {"ids": []}, format="json"
    )

    assert resp.status_code == 400


@pytest.mark.django_db
def test_bulk_delete_without_delete_permission_forbidden(django_user_model, org_a):
    client = custom_role_client(
        django_user_model,
        org_a,
        "viewer@example.com",
        **{ResourceType.LLM_CONFIGS: Permission.READ},
    )
    c = _config(org_a, "c")

    resp = client.post(
        "/api/embedding-configs/bulk-delete/", {"ids": [c.id]}, format="json"
    )

    assert resp.status_code == 403
    assert EmbeddingConfig.objects.filter(id=c.id).exists()


@pytest.mark.django_db
def test_bulk_delete_projects_bucket_visible_proceeds(django_user_model, org_a):
    client = org_admin_client(django_user_model, org_a, "admin@example.com")
    config = _config(org_a, "c")
    crew = Crew.objects.create(org=org_a, name="crew", embedding_config=config)

    projects_usage = by_type(_preview_usage(client, config.id), "projects")
    assert projects_usage["visible_sample"] == [
        {"resource_type": "projects", "kind": "crew", "id": crew.id, "name": crew.name}
    ]

    resp = client.post(
        "/api/embedding-configs/bulk-delete/", {"ids": [config.id]}, format="json"
    )

    assert resp.status_code == 200, resp.data
    crew.refresh_from_db()
    assert crew.embedding_config_id is None


@pytest.mark.django_db
def test_bulk_delete_knowledge_sources_bucket_merges_graphrag_and_naiverag(
    django_user_model, org_a
):
    client = org_admin_client(django_user_model, org_a, "admin@example.com")
    config = _config(org_a, "c")
    collection1 = SourceCollection.objects.create(org=org_a, collection_name="Docs1")
    graph_rag_type = BaseRagType.objects.create(
        source_collection=collection1, rag_type=BaseRagType.RagType.GRAPH
    )
    GraphRag.objects.create(base_rag_type=graph_rag_type, embedder=config)

    collection2 = SourceCollection.objects.create(org=org_a, collection_name="Docs2")
    naive_rag_type = BaseRagType.objects.create(
        source_collection=collection2, rag_type=BaseRagType.RagType.NAIVE
    )
    NaiveRag.objects.create(base_rag_type=naive_rag_type, embedder=config)

    ks_usage = by_type(_preview_usage(client, config.id), "knowledge_sources")
    sample_ids = {item["id"] for item in ks_usage["visible_sample"]}
    assert sample_ids == {collection1.collection_id, collection2.collection_id}
    assert {item["kind"] for item in ks_usage["visible_sample"]} == {"collection"}

    resp = client.post(
        "/api/embedding-configs/bulk-delete/", {"ids": [config.id]}, format="json"
    )

    assert resp.status_code == 200, resp.data


@pytest.mark.django_db
def test_bulk_delete_knowledge_sources_bucket_hidden_blocked(django_user_model, org_a):
    config = _config(org_a, "c")
    collection = SourceCollection.objects.create(org=org_a, collection_name="Docs")
    rag_type = BaseRagType.objects.create(
        source_collection=collection, rag_type=BaseRagType.RagType.GRAPH
    )
    GraphRag.objects.create(base_rag_type=rag_type, embedder=config)

    deleter = custom_role_client(
        django_user_model,
        org_a,
        "deleter@example.com",
        **{ResourceType.LLM_CONFIGS: Permission.DELETE},
    )
    resp = deleter.post(
        "/api/embedding-configs/bulk-delete/", {"ids": [config.id]}, format="json"
    )

    assert resp.status_code == 207, resp.data
    assert resp.data["skipped"] == [{"id": config.id, "reason": "in_use_restricted"}]
    assert EmbeddingConfig.objects.filter(id=config.id).exists()
    usage = _preview_usage(deleter, config.id)
    assert usage["blocked"] is True
    # Nothing about the hidden collection reaches the wire -- not its name, not a count.
    assert by_type(usage, "knowledge_sources") == {
        "resource_type": "knowledge_sources",
        "visible_count": 0,
        "visible_sample": [],
        "truncated": False,
    }


@pytest.mark.django_db
def test_bulk_delete_dry_run_does_not_delete(django_user_model, org_a):
    client = org_admin_client(django_user_model, org_a, "admin@example.com")
    config = _config(org_a, "c")

    resp = client.post(
        "/api/embedding-configs/bulk-delete/?dry_run=true",
        {"ids": [config.id]},
        format="json",
    )

    assert resp.status_code == 200, resp.data
    assert resp.data["dry_run"] is True
    assert resp.data["deleted_ids"] == []
    assert resp.data["deletable_ids"] == [config.id]
    assert EmbeddingConfig.objects.filter(id=config.id).exists()


@pytest.mark.django_db
def test_single_destroy_hidden_usage_blocked(django_user_model, org_a):
    config = _config(org_a, "c")
    Crew.objects.create(org=org_a, name="crew", embedding_config=config)

    deleter = custom_role_client(
        django_user_model,
        org_a,
        "deleter2@example.com",
        **{ResourceType.LLM_CONFIGS: Permission.DELETE},
    )
    resp = deleter.delete(f"/api/embedding-configs/{config.id}/")

    assert resp.status_code == 403, resp.data
    assert resp.data["message"] == "in_use_restricted"
    assert EmbeddingConfig.objects.filter(id=config.id).exists()
