"""Iteration 1 of the backend bulk-delete rollout: GraphViewSet.

Covers the shared response contract (deleted_ids/not_found_ids/skipped_ids),
and the permission-aware `in_use_restricted` guard — a Graph embedded as a
subgraph elsewhere is only deletable if the requester can see the Flow that
embeds it. The guard applies identically to bulk_delete and single destroy.
"""

import pytest
from rest_framework.test import APIClient

from tables.models import Graph
from tables.models.graph_models import SubGraphNode
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
    """A client whose role has exactly `flows_permissions` on FLOWS and
    nothing on any other resource type — used to isolate the "has DELETE but
    not READ" combination the in_use_restricted guard depends on."""
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


@pytest.mark.django_db
def test_bulk_delete_happy_path(django_user_model, org_a):
    client = _org_admin_client(django_user_model, org_a, "admin@example.com")
    g1, g2 = _graph(org_a, "g1"), _graph(org_a, "g2")

    resp = client.post(
        "/api/graphs/bulk-delete/", {"ids": [g1.id, g2.id]}, format="json"
    )

    assert resp.status_code == 200, resp.data
    assert resp.data["deleted_count"] == 2
    assert sorted(resp.data["deleted_ids"]) == sorted([g1.id, g2.id])
    assert resp.data["not_found_ids"] == []
    assert resp.data["skipped_ids"] == []
    assert not Graph.objects.filter(id__in=[g1.id, g2.id]).exists()


@pytest.mark.django_db
def test_bulk_delete_cross_org_id_not_found(django_user_model, org_a, org_b):
    client = _org_admin_client(django_user_model, org_a, "admin@example.com")
    other = _graph(org_b, "other")

    resp = client.post("/api/graphs/bulk-delete/", {"ids": [other.id]}, format="json")

    assert resp.status_code == 207, resp.data
    assert resp.data["not_found_ids"] == [other.id]
    assert resp.data["deleted_ids"] == []
    assert Graph.objects.filter(id=other.id).exists()


@pytest.mark.django_db
def test_bulk_delete_nonexistent_id_not_found(django_user_model, org_a):
    client = _org_admin_client(django_user_model, org_a, "admin@example.com")

    resp = client.post("/api/graphs/bulk-delete/", {"ids": [999999]}, format="json")

    assert resp.status_code == 207, resp.data
    assert resp.data["not_found_ids"] == [999999]


@pytest.mark.django_db
def test_bulk_delete_duplicate_ids_deleted_once(django_user_model, org_a):
    client = _org_admin_client(django_user_model, org_a, "admin@example.com")
    g = _graph(org_a, "g")

    resp = client.post("/api/graphs/bulk-delete/", {"ids": [g.id, g.id]}, format="json")

    assert resp.status_code == 200, resp.data
    assert resp.data["deleted_count"] == 1
    assert resp.data["deleted_ids"] == [g.id]


@pytest.mark.django_db
def test_bulk_delete_empty_ids_rejected(django_user_model, org_a):
    client = _org_admin_client(django_user_model, org_a, "admin@example.com")

    resp = client.post("/api/graphs/bulk-delete/", {"ids": []}, format="json")

    assert resp.status_code == 400


@pytest.mark.django_db
def test_bulk_delete_without_delete_permission_forbidden(django_user_model, org_a):
    # READ-only on FLOWS: can list/retrieve graphs but not delete them.
    client = _custom_role_client(
        django_user_model, org_a, "viewer@example.com", Permission.READ
    )
    g = _graph(org_a, "g")

    resp = client.post("/api/graphs/bulk-delete/", {"ids": [g.id]}, format="json")

    assert resp.status_code == 403
    assert Graph.objects.filter(id=g.id).exists()


@pytest.mark.django_db
def test_bulk_delete_subgraph_usage_visible_proceeds(django_user_model, org_a):
    client = _org_admin_client(django_user_model, org_a, "admin@example.com")
    parent = _graph(org_a, "parent")
    child = _graph(org_a, "child")
    node = SubGraphNode.objects.create(graph=parent, subgraph=child)

    resp = client.post("/api/graphs/bulk-delete/", {"ids": [child.id]}, format="json")

    assert resp.status_code == 200, resp.data
    assert resp.data["deleted_ids"] == [child.id]
    assert not Graph.objects.filter(id=child.id).exists()
    node.refresh_from_db()
    assert node.subgraph_id is None
    # Advisory usage stays in the response even for a real (non-dry-run)
    # delete — it's informational, not preview-only.
    usage = resp.data["usage"][str(child.id)]
    assert usage["blocked"] is False
    assert usage["visible_count"] == 1
    assert usage["visible_sample"] == [{"id": parent.id, "name": parent.name}]


@pytest.mark.django_db
def test_bulk_delete_subgraph_usage_hidden_blocked(django_user_model, org_a):
    # DELETE on FLOWS, but no READ: can call the action but cannot see the
    # parent Flow that embeds this graph as a subgraph.
    client = _custom_role_client(
        django_user_model, org_a, "deleter@example.com", Permission.DELETE
    )
    parent = _graph(org_a, "parent")
    child = _graph(org_a, "child")
    SubGraphNode.objects.create(graph=parent, subgraph=child)

    resp = client.post("/api/graphs/bulk-delete/", {"ids": [child.id]}, format="json")

    assert resp.status_code == 207, resp.data
    assert resp.data["skipped_ids"] == [
        {"id": child.id, "reason": "in_use_restricted"}
    ]
    assert resp.data["deleted_ids"] == []
    assert Graph.objects.filter(id=child.id).exists()
    # Blocked ids still get a usage entry (unified map), but the guard
    # applies today's binary org-level visibility: nothing is disclosed.
    usage = resp.data["usage"][str(child.id)]
    assert usage["blocked"] is True
    assert usage["visible_count"] == 0
    assert usage["visible_sample"] == []


@pytest.mark.django_db
def test_bulk_delete_dry_run_does_not_delete(django_user_model, org_a):
    client = _org_admin_client(django_user_model, org_a, "admin@example.com")
    g = _graph(org_a, "g")

    resp = client.post(
        "/api/graphs/bulk-delete/", {"ids": [g.id], "dry_run": True}, format="json"
    )

    assert resp.status_code == 200, resp.data
    assert resp.data["dry_run"] is True
    assert resp.data["deleted_ids"] == [g.id]
    assert Graph.objects.filter(id=g.id).exists()


@pytest.mark.django_db
def test_bulk_delete_dry_run_shows_visible_usage(django_user_model, org_a):
    client = _org_admin_client(django_user_model, org_a, "admin@example.com")
    parent = _graph(org_a, "parent")
    child = _graph(org_a, "child")
    SubGraphNode.objects.create(graph=parent, subgraph=child)

    resp = client.post(
        "/api/graphs/bulk-delete/", {"ids": [child.id], "dry_run": True}, format="json"
    )

    assert resp.status_code == 200, resp.data
    assert resp.data["deleted_ids"] == [child.id]
    assert Graph.objects.filter(id=child.id).exists()  # dry_run: nothing removed
    usage = resp.data["usage"][str(child.id)]
    assert usage["blocked"] is False
    assert usage["visible_count"] == 1
    assert usage["visible_sample"] == [{"id": parent.id, "name": parent.name}]


@pytest.mark.django_db
def test_bulk_delete_dry_run_still_blocks_hidden_usage(django_user_model, org_a):
    # dry_run doesn't relax the in_use_restricted guard — it only skips the
    # actual delete for ids that would otherwise be allowed through.
    client = _custom_role_client(
        django_user_model, org_a, "deleter3@example.com", Permission.DELETE
    )
    parent = _graph(org_a, "parent")
    child = _graph(org_a, "child")
    SubGraphNode.objects.create(graph=parent, subgraph=child)

    resp = client.post(
        "/api/graphs/bulk-delete/", {"ids": [child.id], "dry_run": True}, format="json"
    )

    assert resp.status_code == 207, resp.data
    assert resp.data["skipped_ids"] == [
        {"id": child.id, "reason": "in_use_restricted"}
    ]
    assert resp.data["deleted_ids"] == []
    assert Graph.objects.filter(id=child.id).exists()


@pytest.mark.django_db
def test_single_destroy_subgraph_usage_hidden_blocked(django_user_model, org_a):
    # Same guard, single-object destroy path — parity with bulk_delete so the
    # block can't be bypassed by deleting one-by-one.
    client = _custom_role_client(
        django_user_model, org_a, "deleter2@example.com", Permission.DELETE
    )
    parent = _graph(org_a, "parent")
    child = _graph(org_a, "child")
    SubGraphNode.objects.create(graph=parent, subgraph=child)

    resp = client.delete(f"/api/graphs/{child.id}/")

    assert resp.status_code == 403, resp.data
    assert Graph.objects.filter(id=child.id).exists()
