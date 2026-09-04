"""Iteration 2 of the backend bulk-delete rollout: CrewReadWriteViewSet
("Project" in the frontend -- there is no standalone Project model/endpoint).

Covers the same shared response contract as Graph (deleted_ids/
not_found_ids/skipped_ids/dry_run/usage), plus the permission-aware
`in_use_restricted` guard checked against TWO referencing sources this time:
`CrewNode.crew` (FLOWS) and `Task.crew` (PROJECTS) -- `usage[id]` carries a
`by_resource_type` list with one entry per source.
"""

import pytest
from rest_framework.test import APIClient

from tables.models import Crew, Graph, PythonCode, Task
from tables.models.graph_models import ConditionalEdge, CrewNode, Edge, StartNode
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


def _custom_role_client(django_user_model, org, email, **resource_permissions):
    """A client whose role has exactly the given permissions per resource
    type (e.g. flows=Permission.DELETE, projects=Permission.DELETE) and
    nothing on any other resource type."""
    role = Role.objects.create(name=f"custom-{email}", is_built_in=False, org=org)
    for resource_type, permissions in resource_permissions.items():
        RolePermission.objects.create(
            role=role, resource_type=resource_type, permissions=int(permissions)
        )
    user = django_user_model.objects.create_user(email=email, password="StrongPass123!")
    OrganizationUser.objects.create(user=user, org=org, role=role)
    c = APIClient()
    c.force_authenticate(user=user)
    c.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
    return c


def _crew(org, name="c"):
    return Crew.objects.create(name=name, org=org)


def _graph(org, name="g"):
    return Graph.objects.create(name=name, metadata={"nodes": [], "edges": []}, org=org)


@pytest.mark.django_db
def test_bulk_delete_happy_path(django_user_model, org_a):
    client = _org_admin_client(django_user_model, org_a, "admin@example.com")
    c1, c2 = _crew(org_a, "c1"), _crew(org_a, "c2")

    resp = client.post("/api/crews/bulk-delete/", {"ids": [c1.id, c2.id]}, format="json")

    assert resp.status_code == 200, resp.data
    assert resp.data["deleted_count"] == 2
    assert sorted(resp.data["deleted_ids"]) == sorted([c1.id, c2.id])
    assert resp.data["not_found_ids"] == []
    assert resp.data["skipped_ids"] == []
    assert not Crew.objects.filter(id__in=[c1.id, c2.id]).exists()


@pytest.mark.django_db
def test_bulk_delete_cross_org_id_not_found(django_user_model, org_a, org_b):
    client = _org_admin_client(django_user_model, org_a, "admin@example.com")
    other = _crew(org_b, "other")

    resp = client.post("/api/crews/bulk-delete/", {"ids": [other.id]}, format="json")

    assert resp.status_code == 207, resp.data
    assert resp.data["not_found_ids"] == [other.id]
    assert Crew.objects.filter(id=other.id).exists()


@pytest.mark.django_db
def test_bulk_delete_nonexistent_id_not_found(django_user_model, org_a):
    client = _org_admin_client(django_user_model, org_a, "admin@example.com")

    resp = client.post("/api/crews/bulk-delete/", {"ids": [999999]}, format="json")

    assert resp.status_code == 207, resp.data
    assert resp.data["not_found_ids"] == [999999]


@pytest.mark.django_db
def test_bulk_delete_duplicate_ids_deleted_once(django_user_model, org_a):
    client = _org_admin_client(django_user_model, org_a, "admin@example.com")
    c = _crew(org_a, "c")

    resp = client.post("/api/crews/bulk-delete/", {"ids": [c.id, c.id]}, format="json")

    assert resp.status_code == 200, resp.data
    assert resp.data["deleted_count"] == 1
    assert resp.data["deleted_ids"] == [c.id]


@pytest.mark.django_db
def test_bulk_delete_empty_ids_rejected(django_user_model, org_a):
    client = _org_admin_client(django_user_model, org_a, "admin@example.com")

    resp = client.post("/api/crews/bulk-delete/", {"ids": []}, format="json")

    assert resp.status_code == 400


@pytest.mark.django_db
def test_bulk_delete_without_delete_permission_forbidden(django_user_model, org_a):
    client = _custom_role_client(
        django_user_model, org_a, "viewer@example.com",
        **{ResourceType.PROJECTS: Permission.READ},
    )
    c = _crew(org_a, "c")

    resp = client.post("/api/crews/bulk-delete/", {"ids": [c.id]}, format="json")

    assert resp.status_code == 403
    assert Crew.objects.filter(id=c.id).exists()


@pytest.mark.django_db
def test_bulk_delete_crew_node_usage_visible_proceeds_and_cleans_edges(
    django_user_model, org_a
):
    client = _org_admin_client(django_user_model, org_a, "admin@example.com")
    graph = _graph(org_a, "flow")
    crew = _crew(org_a, "crew")
    node = CrewNode.objects.create(graph=graph, crew=crew)
    other_node = StartNode.objects.create(graph=graph, variables={})
    edge = Edge.objects.create(
        graph=graph, start_node_id=node.id, end_node_id=other_node.id
    )
    cond_edge = ConditionalEdge.objects.create(
        graph=graph,
        source_node_id=node.id,
        python_code=PythonCode.objects.create(code=""),
    )

    resp = client.post("/api/crews/bulk-delete/", {"ids": [crew.id]}, format="json")

    assert resp.status_code == 200, resp.data
    assert resp.data["deleted_ids"] == [crew.id]
    assert not Crew.objects.filter(id=crew.id).exists()
    assert not CrewNode.objects.filter(id=node.id).exists()  # cascaded
    # The dangling-Edge structural bug fix: cascaded CrewNode deletion must
    # clean up Edge/ConditionalEdge rows pointing at it (no FK, no cascade).
    assert not Edge.objects.filter(id=edge.id).exists()
    assert not ConditionalEdge.objects.filter(id=cond_edge.id).exists()


@pytest.mark.django_db
def test_bulk_delete_crew_node_usage_hidden_blocked(django_user_model, org_a):
    # DELETE on PROJECTS (to call the action) but no READ on FLOWS: cannot
    # see the Flow that embeds this crew via CrewNode.
    client = _custom_role_client(
        django_user_model, org_a, "deleter@example.com",
        **{ResourceType.PROJECTS: Permission.DELETE},
    )
    graph = _graph(org_a, "flow")
    crew = _crew(org_a, "crew")
    CrewNode.objects.create(graph=graph, crew=crew)

    resp = client.post("/api/crews/bulk-delete/", {"ids": [crew.id]}, format="json")

    assert resp.status_code == 207, resp.data
    assert resp.data["skipped_ids"] == [{"id": crew.id, "reason": "in_use_restricted"}]
    assert resp.data["deleted_ids"] == []
    assert Crew.objects.filter(id=crew.id).exists()
    usage = resp.data["usage"][str(crew.id)]
    assert usage["blocked"] is True
    flows_usage = next(
        s for s in usage["by_resource_type"] if s["resource_type"] == "flows"
    )
    assert flows_usage["visible_count"] == 0
    assert flows_usage["visible_sample"] == []


@pytest.mark.django_db
def test_bulk_delete_task_only_usage_not_blocked(django_user_model, org_a):
    # Crew referenced only by a Task (same PROJECTS bucket as the delete
    # permission) -- not blocked; Task.crew ends up NULL.
    client = _org_admin_client(django_user_model, org_a, "admin@example.com")
    crew = _crew(org_a, "crew")
    task = Task.objects.create(
        crew=crew, name="t", instructions="do it", expected_output="out"
    )

    resp = client.post("/api/crews/bulk-delete/", {"ids": [crew.id]}, format="json")

    assert resp.status_code == 200, resp.data
    assert resp.data["deleted_ids"] == [crew.id]
    assert not Crew.objects.filter(id=crew.id).exists()
    task.refresh_from_db()
    assert task.crew_id is None


@pytest.mark.django_db
def test_bulk_delete_mixed_usage_has_two_resource_types(django_user_model, org_a):
    client = _org_admin_client(django_user_model, org_a, "admin@example.com")
    graph = _graph(org_a, "flow")
    crew = _crew(org_a, "crew")
    CrewNode.objects.create(graph=graph, crew=crew)
    Task.objects.create(
        crew=crew, name="t", instructions="do it", expected_output="out"
    )

    resp = client.post("/api/crews/bulk-delete/", {"ids": [crew.id]}, format="json")

    assert resp.status_code == 200, resp.data
    usage = resp.data["usage"][str(crew.id)]
    resource_types = {s["resource_type"] for s in usage["by_resource_type"]}
    assert resource_types == {"flows", "projects"}


@pytest.mark.django_db
def test_single_destroy_crew_node_usage_hidden_blocked(django_user_model, org_a):
    client = _custom_role_client(
        django_user_model, org_a, "deleter2@example.com",
        **{ResourceType.PROJECTS: Permission.DELETE},
    )
    graph = _graph(org_a, "flow")
    crew = _crew(org_a, "crew")
    CrewNode.objects.create(graph=graph, crew=crew)

    resp = client.delete(f"/api/crews/{crew.id}/")

    assert resp.status_code == 403, resp.data
    assert Crew.objects.filter(id=crew.id).exists()


@pytest.mark.django_db
def test_bulk_delete_dry_run_does_not_delete(django_user_model, org_a):
    client = _org_admin_client(django_user_model, org_a, "admin@example.com")
    crew = _crew(org_a, "crew")

    resp = client.post(
        "/api/crews/bulk-delete/", {"ids": [crew.id], "dry_run": True}, format="json"
    )

    assert resp.status_code == 200, resp.data
    assert resp.data["dry_run"] is True
    assert resp.data["deleted_ids"] == [crew.id]
    assert Crew.objects.filter(id=crew.id).exists()


@pytest.mark.django_db
def test_bulk_delete_dry_run_still_blocks_hidden_usage(django_user_model, org_a):
    client = _custom_role_client(
        django_user_model, org_a, "deleter3@example.com",
        **{ResourceType.PROJECTS: Permission.DELETE},
    )
    graph = _graph(org_a, "flow")
    crew = _crew(org_a, "crew")
    CrewNode.objects.create(graph=graph, crew=crew)

    resp = client.post(
        "/api/crews/bulk-delete/", {"ids": [crew.id], "dry_run": True}, format="json"
    )

    assert resp.status_code == 207, resp.data
    assert resp.data["skipped_ids"] == [{"id": crew.id, "reason": "in_use_restricted"}]
    assert Crew.objects.filter(id=crew.id).exists()
