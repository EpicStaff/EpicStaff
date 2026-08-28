"""Iteration 3 of the backend bulk-delete rollout: AgentViewSet ("staff"
agents -- the classic `tables.Agent` model, deprecated but kept for
backward-compatibility cleanup of legacy rows; NOT the new `agents.
AgentDefinition`).

Covers the same shared response contract as Graph/Crew (deleted_ids/
not_found_ids/skipped_ids/dry_run/usage), plus the permission-aware
`in_use_restricted` guard checked against two sources merged into ONE
`PROJECTS` entry: `Crew.agents` (M2M) and `Task.agent` (FK) -- both live
under the same resource type, so `usage[id].by_resource_type` has a single
`"projects"` entry combining both.
"""

import pytest
from rest_framework.test import APIClient

from tables.models import Agent, Crew, Task
from tables.models.realtime_models import RealtimeAgent
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


def _agent(org, role="a"):
    return Agent.objects.create(org=org, role=role, goal="g", backstory="b")


def _crew(org, name="c"):
    return Crew.objects.create(name=name, org=org)


@pytest.mark.django_db
def test_bulk_delete_happy_path(django_user_model, org_a):
    client = _org_admin_client(django_user_model, org_a, "admin@example.com")
    a1, a2 = _agent(org_a, "a1"), _agent(org_a, "a2")

    resp = client.post("/api/agents/bulk-delete/", {"ids": [a1.id, a2.id]}, format="json")

    assert resp.status_code == 200, resp.data
    assert resp.data["deleted_count"] == 2
    assert sorted(resp.data["deleted_ids"]) == sorted([a1.id, a2.id])
    assert resp.data["not_found_ids"] == []
    assert resp.data["skipped_ids"] == []
    assert not Agent.objects.filter(id__in=[a1.id, a2.id]).exists()


@pytest.mark.django_db
def test_bulk_delete_cross_org_id_not_found(django_user_model, org_a, org_b):
    client = _org_admin_client(django_user_model, org_a, "admin@example.com")
    other = _agent(org_b, "other")

    resp = client.post("/api/agents/bulk-delete/", {"ids": [other.id]}, format="json")

    assert resp.status_code == 207, resp.data
    assert resp.data["not_found_ids"] == [other.id]
    assert Agent.objects.filter(id=other.id).exists()


@pytest.mark.django_db
def test_bulk_delete_nonexistent_id_not_found(django_user_model, org_a):
    client = _org_admin_client(django_user_model, org_a, "admin@example.com")

    resp = client.post("/api/agents/bulk-delete/", {"ids": [999999]}, format="json")

    assert resp.status_code == 207, resp.data
    assert resp.data["not_found_ids"] == [999999]


@pytest.mark.django_db
def test_bulk_delete_duplicate_ids_deleted_once(django_user_model, org_a):
    client = _org_admin_client(django_user_model, org_a, "admin@example.com")
    a = _agent(org_a, "a")

    resp = client.post("/api/agents/bulk-delete/", {"ids": [a.id, a.id]}, format="json")

    assert resp.status_code == 200, resp.data
    assert resp.data["deleted_count"] == 1
    assert resp.data["deleted_ids"] == [a.id]


@pytest.mark.django_db
def test_bulk_delete_empty_ids_rejected(django_user_model, org_a):
    client = _org_admin_client(django_user_model, org_a, "admin@example.com")

    resp = client.post("/api/agents/bulk-delete/", {"ids": []}, format="json")

    assert resp.status_code == 400


@pytest.mark.django_db
def test_bulk_delete_without_delete_permission_forbidden(django_user_model, org_a):
    client = _custom_role_client(
        django_user_model, org_a, "viewer@example.com",
        **{ResourceType.AGENTS: Permission.READ},
    )
    a = _agent(org_a, "a")

    resp = client.post("/api/agents/bulk-delete/", {"ids": [a.id]}, format="json")

    assert resp.status_code == 403
    assert Agent.objects.filter(id=a.id).exists()


@pytest.mark.django_db
def test_bulk_delete_crew_usage_visible_proceeds(django_user_model, org_a):
    client = _org_admin_client(django_user_model, org_a, "admin@example.com")
    agent = _agent(org_a, "a")
    crew = _crew(org_a, "crew")
    crew.agents.add(agent)

    resp = client.post("/api/agents/bulk-delete/", {"ids": [agent.id]}, format="json")

    assert resp.status_code == 200, resp.data
    assert resp.data["deleted_ids"] == [agent.id]
    assert not Agent.objects.filter(id=agent.id).exists()
    assert not crew.agents.filter(id=agent.id).exists()
    usage = resp.data["usage"][str(agent.id)]
    assert usage["blocked"] is False
    projects_usage = usage["by_resource_type"][0]
    assert projects_usage["resource_type"] == "projects"
    assert projects_usage["visible_count"] == 1
    assert projects_usage["visible_sample"] == [{"id": crew.id, "name": crew.name}]


@pytest.mark.django_db
def test_bulk_delete_task_usage_visible_proceeds(django_user_model, org_a):
    client = _org_admin_client(django_user_model, org_a, "admin@example.com")
    agent = _agent(org_a, "a")
    crew = _crew(org_a, "crew")
    task = Task.objects.create(
        crew=crew, agent=agent, name="t", instructions="do it", expected_output="out"
    )

    resp = client.post("/api/agents/bulk-delete/", {"ids": [agent.id]}, format="json")

    assert resp.status_code == 200, resp.data
    assert not Agent.objects.filter(id=agent.id).exists()
    task.refresh_from_db()
    assert task.agent_id is None


@pytest.mark.django_db
def test_bulk_delete_mixed_crew_and_task_usage_merged_into_one_entry(
    django_user_model, org_a
):
    client = _org_admin_client(django_user_model, org_a, "admin@example.com")
    agent = _agent(org_a, "a")
    crew = _crew(org_a, "crew")
    crew.agents.add(agent)
    task = Task.objects.create(
        crew=crew, agent=agent, name="t", instructions="do it", expected_output="out"
    )

    resp = client.post(
        "/api/agents/bulk-delete/", {"ids": [agent.id], "dry_run": True}, format="json"
    )

    assert resp.status_code == 200, resp.data
    usage = resp.data["usage"][str(agent.id)]
    assert len(usage["by_resource_type"]) == 1
    projects_usage = usage["by_resource_type"][0]
    assert projects_usage["visible_count"] == 2
    sample_ids = {item["id"] for item in projects_usage["visible_sample"]}
    assert sample_ids == {crew.id, task.id}


@pytest.mark.django_db
def test_bulk_delete_usage_hidden_blocked(django_user_model, org_a):
    # DELETE on AGENTS (to call the action) but no READ on PROJECTS: cannot
    # see the Crew that this agent is assigned to.
    client = _custom_role_client(
        django_user_model, org_a, "deleter@example.com",
        **{ResourceType.AGENTS: Permission.DELETE},
    )
    agent = _agent(org_a, "a")
    crew = _crew(org_a, "crew")
    crew.agents.add(agent)

    resp = client.post("/api/agents/bulk-delete/", {"ids": [agent.id]}, format="json")

    assert resp.status_code == 207, resp.data
    assert resp.data["skipped_ids"] == [{"id": agent.id, "reason": "in_use_restricted"}]
    assert resp.data["deleted_ids"] == []
    assert Agent.objects.filter(id=agent.id).exists()
    usage = resp.data["usage"][str(agent.id)]
    assert usage["blocked"] is True
    projects_usage = usage["by_resource_type"][0]
    assert projects_usage["visible_count"] == 0
    assert projects_usage["visible_sample"] == []


@pytest.mark.django_db
def test_bulk_delete_realtime_agent_cascade_not_a_usage_source(
    django_user_model, org_a
):
    client = _org_admin_client(django_user_model, org_a, "admin@example.com")
    agent = _agent(org_a, "a")
    RealtimeAgent.objects.create(agent=agent)

    resp = client.post("/api/agents/bulk-delete/", {"ids": [agent.id]}, format="json")

    assert resp.status_code == 200, resp.data
    assert resp.data["deleted_ids"] == [agent.id]
    assert not Agent.objects.filter(id=agent.id).exists()
    assert not RealtimeAgent.objects.filter(agent_id=agent.id).exists()


@pytest.mark.django_db
def test_single_destroy_usage_hidden_blocked(django_user_model, org_a):
    client = _custom_role_client(
        django_user_model, org_a, "deleter2@example.com",
        **{ResourceType.AGENTS: Permission.DELETE},
    )
    agent = _agent(org_a, "a")
    crew = _crew(org_a, "crew")
    crew.agents.add(agent)

    resp = client.delete(f"/api/agents/{agent.id}/")

    assert resp.status_code == 403, resp.data
    assert Agent.objects.filter(id=agent.id).exists()


@pytest.mark.django_db
def test_bulk_delete_dry_run_does_not_delete(django_user_model, org_a):
    client = _org_admin_client(django_user_model, org_a, "admin@example.com")
    agent = _agent(org_a, "a")

    resp = client.post(
        "/api/agents/bulk-delete/", {"ids": [agent.id], "dry_run": True}, format="json"
    )

    assert resp.status_code == 200, resp.data
    assert resp.data["dry_run"] is True
    assert resp.data["deleted_ids"] == [agent.id]
    assert Agent.objects.filter(id=agent.id).exists()
