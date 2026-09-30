"""API tests for GraphVersionViewSet bulk delete, through BulkDeleteActionMixin.

GraphVersion has zero referencing sources anywhere in the schema -- nothing
holds an FK to it -- so the in_use_restricted guard can never fire. Its response
still has exactly the family's shape: `skipped` and `usage` are present and
empty rather than absent, so a client needs no per-entity branch.
"""

import pytest

from tables.models import Graph, GraphVersion
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


def _graph(org, name="g"):
    return Graph.objects.create(name=name, metadata={"nodes": [], "edges": []}, org=org)


def _version(graph, name="v1"):
    return GraphVersion.objects.create(graph=graph, name=name, snapshot={})


@pytest.mark.django_db
def test_bulk_delete_happy_path(django_user_model, org_a):
    client = org_admin_client(django_user_model, org_a, "admin@example.com")
    graph = _graph(org_a)
    v1, v2 = _version(graph, "v1"), _version(graph, "v2")

    resp = client.post(
        "/api/graph-versions/bulk-delete/", {"ids": [v1.id, v2.id]}, format="json"
    )

    assert resp.status_code == 200, resp.data
    assert resp.data["deleted_count"] == 2
    assert sorted(resp.data["deleted_ids"]) == sorted([v1.id, v2.id])
    assert resp.data["not_found_ids"] == []
    assert resp.data["skipped"] == []
    assert resp.data["usage"] == {}
    assert not GraphVersion.objects.filter(id__in=[v1.id, v2.id]).exists()


@pytest.mark.django_db
def test_bulk_delete_cross_org_id_not_found(django_user_model, org_a, org_b):
    client = org_admin_client(django_user_model, org_a, "admin@example.com")
    other_graph = _graph(org_b, "other")
    other_version = _version(other_graph)

    resp = client.post(
        "/api/graph-versions/bulk-delete/", {"ids": [other_version.id]}, format="json"
    )

    assert resp.status_code == 207, resp.data
    assert resp.data["not_found_ids"] == [other_version.id]
    assert resp.data["deleted_ids"] == []
    assert GraphVersion.objects.filter(id=other_version.id).exists()


@pytest.mark.django_db
def test_bulk_delete_nonexistent_id_not_found(django_user_model, org_a):
    client = org_admin_client(django_user_model, org_a, "admin@example.com")

    resp = client.post(
        "/api/graph-versions/bulk-delete/", {"ids": [999999]}, format="json"
    )

    assert resp.status_code == 207, resp.data
    assert resp.data["not_found_ids"] == [999999]


@pytest.mark.django_db
def test_bulk_delete_duplicate_ids_deleted_once(django_user_model, org_a):
    client = org_admin_client(django_user_model, org_a, "admin@example.com")
    graph = _graph(org_a)
    v = _version(graph)

    resp = client.post(
        "/api/graph-versions/bulk-delete/", {"ids": [v.id, v.id]}, format="json"
    )

    assert resp.status_code == 200, resp.data
    assert resp.data["deleted_count"] == 1
    assert resp.data["deleted_ids"] == [v.id]


@pytest.mark.django_db
def test_bulk_delete_empty_ids_rejected(django_user_model, org_a):
    client = org_admin_client(django_user_model, org_a, "admin@example.com")

    resp = client.post("/api/graph-versions/bulk-delete/", {"ids": []}, format="json")

    assert resp.status_code == 400


@pytest.mark.django_db
def test_bulk_delete_without_delete_permission_forbidden(django_user_model, org_a):
    client = custom_role_client(
        django_user_model,
        org_a,
        "viewer@example.com",
        **{ResourceType.FLOWS: Permission.READ},
    )
    graph = _graph(org_a)
    v = _version(graph)

    resp = client.post(
        "/api/graph-versions/bulk-delete/", {"ids": [v.id]}, format="json"
    )

    assert resp.status_code == 403
    assert GraphVersion.objects.filter(id=v.id).exists()


@pytest.mark.django_db
def test_bulk_delete_response_shares_the_family_shape(django_user_model, org_a):
    """`skipped` and `usage` are present and empty, never absent.

    GraphVersion can never be blocked, but "permanently empty" is an
    argument for empty, not for absent -- the same key set as every other
    entity means a client needs no GraphVersion special case.
    """
    client = org_admin_client(django_user_model, org_a, "admin@example.com")
    graph = _graph(org_a)
    v = _version(graph)

    resp = client.post(
        "/api/graph-versions/bulk-delete/", {"ids": [v.id]}, format="json"
    )

    assert resp.status_code == 200, resp.data
    assert set(resp.data.keys()) == {
        "dry_run",
        "deleted_count",
        "deleted_ids",
        "deletable_ids",
        "not_found_ids",
        "skipped",
        "usage",
    }
    assert resp.data["skipped"] == []
    assert resp.data["usage"] == {}


@pytest.mark.django_db
def test_bulk_delete_dry_run_does_not_delete(django_user_model, org_a):
    client = org_admin_client(django_user_model, org_a, "admin@example.com")
    graph = _graph(org_a)
    v = _version(graph)

    resp = client.post(
        "/api/graph-versions/bulk-delete/?dry_run=true", {"ids": [v.id]}, format="json"
    )

    assert resp.status_code == 200, resp.data
    assert resp.data["dry_run"] is True
    assert resp.data["deleted_ids"] == []
    assert resp.data["deletable_ids"] == [v.id]
    # The preview reports one empty usage entry per id: nothing references it.
    assert resp.data["usage"] == {str(v.id): {"blocked": False, "by_resource_type": []}}
    assert GraphVersion.objects.filter(id=v.id).exists()


@pytest.mark.django_db
def test_single_destroy_still_works(django_user_model, org_a):
    # Parity check: adding perform_destroy shouldn't change single-DELETE
    # behavior for GraphVersion, since the guard is a structural no-op here.
    client = org_admin_client(django_user_model, org_a, "admin@example.com")
    graph = _graph(org_a)
    v = _version(graph)

    resp = client.delete(f"/api/graph-versions/{v.id}/")

    assert resp.status_code == 204, resp.data
    assert not GraphVersion.objects.filter(id=v.id).exists()
