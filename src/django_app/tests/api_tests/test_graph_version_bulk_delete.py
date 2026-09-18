"""Iteration 9 of the backend bulk-delete rollout: GraphVersionViewSet.

Unlike every prior entity in this rollout, GraphVersion has zero referencing
sources anywhere in the schema -- nothing holds an FK to it, so the
permission-aware in_use_restricted guard can never fire. The response is
correspondingly slimmer than every other entity: no `skipped_ids`/`usage`
keys, since both would be permanently empty/vacuous here.
"""

import pytest
from rest_framework.test import APIClient

from tables.models import Graph, GraphVersion
from tables.models.rbac_models import Organization, OrganizationUser, Role, RolePermission
from tables.models.rbac_models.rbac_enums import BuiltInRole, Permission, ResourceType


@pytest.fixture
def org_a(db):
    return Organization.objects.create(name="Org A")


@pytest.fixture
def org_b(db):
    return Organization.objects.create(name="Org B")


def _org_admin_client(django_user_model, org, email):
    role = Role.objects.get(
        name=BuiltInRole.ORG_ADMIN, is_built_in=True, org__isnull=True
    )
    user = django_user_model.objects.create_user(email=email, password="StrongPass123!")
    OrganizationUser.objects.create(user=user, org=org, role=role)
    c = APIClient()
    c.force_authenticate(user=user)
    c.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
    return c


def _custom_role_client(django_user_model, org, email, flows_permissions):
    role = Role.objects.create(name=f"custom-{email}", is_built_in=False, org=org)
    RolePermission.objects.create(
        role=role, resource_type=ResourceType.FLOWS, permissions=int(flows_permissions)
    )
    user = django_user_model.objects.create_user(email=email, password="StrongPass123!")
    OrganizationUser.objects.create(user=user, org=org, role=role)
    c = APIClient()
    c.force_authenticate(user=user)
    c.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
    return c


def _graph(org, name="g"):
    return Graph.objects.create(name=name, metadata={"nodes": [], "edges": []}, org=org)


def _version(graph, name="v1"):
    return GraphVersion.objects.create(graph=graph, name=name, snapshot={})


@pytest.mark.django_db
def test_bulk_delete_happy_path(django_user_model, org_a):
    client = _org_admin_client(django_user_model, org_a, "admin@example.com")
    graph = _graph(org_a)
    v1, v2 = _version(graph, "v1"), _version(graph, "v2")

    resp = client.post(
        "/api/graph-versions/bulk-delete/", {"ids": [v1.id, v2.id]}, format="json"
    )

    assert resp.status_code == 200, resp.data
    assert resp.data["deleted_count"] == 2
    assert sorted(resp.data["deleted_ids"]) == sorted([v1.id, v2.id])
    assert resp.data["not_found_ids"] == []
    assert "skipped_ids" not in resp.data
    assert "usage" not in resp.data
    assert not GraphVersion.objects.filter(id__in=[v1.id, v2.id]).exists()


@pytest.mark.django_db
def test_bulk_delete_cross_org_id_not_found(django_user_model, org_a, org_b):
    client = _org_admin_client(django_user_model, org_a, "admin@example.com")
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
    client = _org_admin_client(django_user_model, org_a, "admin@example.com")

    resp = client.post(
        "/api/graph-versions/bulk-delete/", {"ids": [999999]}, format="json"
    )

    assert resp.status_code == 207, resp.data
    assert resp.data["not_found_ids"] == [999999]


@pytest.mark.django_db
def test_bulk_delete_duplicate_ids_deleted_once(django_user_model, org_a):
    client = _org_admin_client(django_user_model, org_a, "admin@example.com")
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
    client = _org_admin_client(django_user_model, org_a, "admin@example.com")

    resp = client.post("/api/graph-versions/bulk-delete/", {"ids": []}, format="json")

    assert resp.status_code == 400


@pytest.mark.django_db
def test_bulk_delete_without_delete_permission_forbidden(django_user_model, org_a):
    client = _custom_role_client(
        django_user_model, org_a, "viewer@example.com", Permission.READ
    )
    graph = _graph(org_a)
    v = _version(graph)

    resp = client.post(
        "/api/graph-versions/bulk-delete/", {"ids": [v.id]}, format="json"
    )

    assert resp.status_code == 403
    assert GraphVersion.objects.filter(id=v.id).exists()


@pytest.mark.django_db
def test_bulk_delete_response_has_no_usage_or_skipped_keys(django_user_model, org_a):
    # GraphVersion can never be blocked (no referencing sources exist), so
    # unlike every other entity in this rollout, skipped_ids/usage are
    # omitted entirely rather than shipped as permanently-vacuous fields.
    client = _org_admin_client(django_user_model, org_a, "admin@example.com")
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
        "not_found_ids",
    }


@pytest.mark.django_db
def test_bulk_delete_dry_run_does_not_delete(django_user_model, org_a):
    client = _org_admin_client(django_user_model, org_a, "admin@example.com")
    graph = _graph(org_a)
    v = _version(graph)

    resp = client.post(
        "/api/graph-versions/bulk-delete/",
        {"ids": [v.id], "dry_run": True},
        format="json",
    )

    assert resp.status_code == 200, resp.data
    assert resp.data["dry_run"] is True
    assert resp.data["deleted_ids"] == [v.id]
    assert GraphVersion.objects.filter(id=v.id).exists()


@pytest.mark.django_db
def test_single_destroy_still_works(django_user_model, org_a):
    # Parity check: adding perform_destroy shouldn't change single-DELETE
    # behavior for GraphVersion, since the guard is a structural no-op here.
    client = _org_admin_client(django_user_model, org_a, "admin@example.com")
    graph = _graph(org_a)
    v = _version(graph)

    resp = client.delete(f"/api/graph-versions/{v.id}/")

    assert resp.status_code == 204, resp.data
    assert not GraphVersion.objects.filter(id=v.id).exists()
