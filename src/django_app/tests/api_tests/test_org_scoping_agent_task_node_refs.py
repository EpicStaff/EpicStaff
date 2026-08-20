"""Cross-org reference rejection for AgentNode/TaskNode (security regression tests).

`agent_definition`, `surface_list`, and `graph` on AgentNodeSerializer /
TaskNodeSerializer used plain (unscoped) PrimaryKeyRelatedField via
`fields = "__all__"`, so a pk from another org was silently accepted — most
notably `agent_definition` with an empty `surface_list`, which no existing
validator caught. Each of the three FKs must now be rejected exactly like a
non-existent pk (no cross-org existence leak), and same-org references must
keep working.
"""

import pytest
from rest_framework.test import APIClient

from agents.models import AgentDefinition
from agents.models.surface_models import Surface
from tables.models.graph_models import AgentNode, Graph, TaskNode
from tables.models.rbac_models import Organization, OrganizationUser, Role
from tables.models.rbac_models.rbac_enums import BuiltInRole


@pytest.fixture
def role_admin(db):
    return Role.objects.get(
        name=BuiltInRole.ORG_ADMIN, is_built_in=True, org__isnull=True
    )


@pytest.fixture
def org_a(db):
    return Organization.objects.create(name="Org A")


@pytest.fixture
def org_b(db):
    return Organization.objects.create(name="Org B")


@pytest.fixture
def client_a(db, django_user_model, org_a, role_admin):
    user = django_user_model.objects.create_user(
        email="admin_a@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=org_a, role=role_admin)
    client = APIClient()
    client.force_authenticate(user=user)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(org_a.id))
    return client


def _rejected(resp):
    return resp.status_code == 400 and "does not exist" in str(resp.data)


# ---- TaskNode: agent_definition ----


@pytest.mark.django_db
def test_tasknode_create_rejects_cross_org_agent_definition(client_a, org_a, org_b):
    graph = Graph.objects.create(name="a-graph", org=org_a)
    b_agent_definition = AgentDefinition.objects.create(name="adb", organization=org_b)
    resp = client_a.post(
        "/api/tasknodes/",
        {"graph": graph.id, "agent_definition": b_agent_definition.id},
        format="json",
    )
    assert _rejected(resp), resp.data
    assert not TaskNode.objects.filter(graph=graph).exists()


@pytest.mark.django_db
def test_tasknode_update_rejects_cross_org_agent_definition(client_a, org_a, org_b):
    graph = Graph.objects.create(name="a-graph", org=org_a)
    node = TaskNode.objects.create(graph=graph, node_name="ta")
    b_agent_definition = AgentDefinition.objects.create(name="adb", organization=org_b)
    resp = client_a.patch(
        f"/api/tasknodes/{node.id}/",
        {"agent_definition": b_agent_definition.id},
        format="json",
    )
    assert _rejected(resp), resp.data
    node.refresh_from_db()
    assert node.agent_definition_id is None


@pytest.mark.django_db
def test_tasknode_create_allows_same_org_agent_definition(client_a, org_a):
    graph = Graph.objects.create(name="a-graph", org=org_a)
    a_agent_definition = AgentDefinition.objects.create(name="ada", organization=org_a)
    resp = client_a.post(
        "/api/tasknodes/",
        {"graph": graph.id, "agent_definition": a_agent_definition.id},
        format="json",
    )
    assert resp.status_code == 201, resp.data
    assert (
        TaskNode.objects.get(id=resp.data["id"]).agent_definition_id
        == a_agent_definition.id
    )


# ---- TaskNode: surface_list ----


@pytest.mark.django_db
def test_tasknode_create_rejects_cross_org_surface(client_a, org_a, org_b):
    graph = Graph.objects.create(name="a-graph", org=org_a)
    b_surface = Surface.objects.create(name="sb", organization=org_b)
    resp = client_a.post(
        "/api/tasknodes/",
        {"graph": graph.id, "surface_list": [b_surface.id]},
        format="json",
    )
    assert _rejected(resp), resp.data
    assert not TaskNode.objects.filter(graph=graph).exists()


@pytest.mark.django_db
def test_tasknode_create_allows_same_org_surface(client_a, org_a):
    graph = Graph.objects.create(name="a-graph", org=org_a)
    a_surface = Surface.objects.create(name="sa", organization=org_a)
    resp = client_a.post(
        "/api/tasknodes/",
        {"graph": graph.id, "surface_list": [a_surface.id]},
        format="json",
    )
    assert resp.status_code == 201, resp.data
    assert list(
        TaskNode.objects.get(id=resp.data["id"]).surface_list.values_list(
            "id", flat=True
        )
    ) == [a_surface.id]


# ---- TaskNode: graph ----


@pytest.mark.django_db
def test_tasknode_create_rejects_cross_org_graph(client_a, org_b):
    b_graph = Graph.objects.create(name="b-graph", org=org_b)
    resp = client_a.post(
        "/api/tasknodes/",
        {"graph": b_graph.id},
        format="json",
    )
    assert _rejected(resp), resp.data
    assert not TaskNode.objects.filter(graph=b_graph).exists()


# ---- AgentNode: agent_definition ----


@pytest.mark.django_db
def test_agentnode_create_rejects_cross_org_agent_definition(client_a, org_a, org_b):
    graph = Graph.objects.create(name="a-graph", org=org_a)
    b_agent_definition = AgentDefinition.objects.create(name="adb", organization=org_b)
    resp = client_a.post(
        "/api/agentnodes/",
        {"graph": graph.id, "agent_definition": b_agent_definition.id},
        format="json",
    )
    assert _rejected(resp), resp.data
    assert not AgentNode.objects.filter(graph=graph).exists()


@pytest.mark.django_db
def test_agentnode_update_rejects_cross_org_agent_definition(client_a, org_a, org_b):
    graph = Graph.objects.create(name="a-graph", org=org_a)
    node = AgentNode.objects.create(graph=graph, node_name="aa")
    b_agent_definition = AgentDefinition.objects.create(name="adb", organization=org_b)
    resp = client_a.patch(
        f"/api/agentnodes/{node.id}/",
        {"agent_definition": b_agent_definition.id},
        format="json",
    )
    assert _rejected(resp), resp.data
    node.refresh_from_db()
    assert node.agent_definition_id is None


@pytest.mark.django_db
def test_agentnode_create_allows_same_org_agent_definition(client_a, org_a):
    graph = Graph.objects.create(name="a-graph", org=org_a)
    a_agent_definition = AgentDefinition.objects.create(name="ada", organization=org_a)
    resp = client_a.post(
        "/api/agentnodes/",
        {"graph": graph.id, "agent_definition": a_agent_definition.id},
        format="json",
    )
    assert resp.status_code == 201, resp.data
    assert (
        AgentNode.objects.get(id=resp.data["id"]).agent_definition_id
        == a_agent_definition.id
    )


# ---- AgentNode: surface_list ----


@pytest.mark.django_db
def test_agentnode_create_rejects_cross_org_surface(client_a, org_a, org_b):
    graph = Graph.objects.create(name="a-graph", org=org_a)
    b_surface = Surface.objects.create(name="sb", organization=org_b)
    resp = client_a.post(
        "/api/agentnodes/",
        {"graph": graph.id, "surface_list": [b_surface.id]},
        format="json",
    )
    assert _rejected(resp), resp.data
    assert not AgentNode.objects.filter(graph=graph).exists()


@pytest.mark.django_db
def test_agentnode_create_allows_same_org_surface(client_a, org_a):
    graph = Graph.objects.create(name="a-graph", org=org_a)
    a_surface = Surface.objects.create(name="sa", organization=org_a)
    resp = client_a.post(
        "/api/agentnodes/",
        {"graph": graph.id, "surface_list": [a_surface.id]},
        format="json",
    )
    assert resp.status_code == 201, resp.data
    assert list(
        AgentNode.objects.get(id=resp.data["id"]).surface_list.values_list(
            "id", flat=True
        )
    ) == [a_surface.id]


# ---- AgentNode: graph ----


@pytest.mark.django_db
def test_agentnode_create_rejects_cross_org_graph(client_a, org_b):
    b_graph = Graph.objects.create(name="b-graph", org=org_b)
    resp = client_a.post(
        "/api/agentnodes/",
        {"graph": b_graph.id},
        format="json",
    )
    assert _rejected(resp), resp.data
    assert not AgentNode.objects.filter(graph=b_graph).exists()
