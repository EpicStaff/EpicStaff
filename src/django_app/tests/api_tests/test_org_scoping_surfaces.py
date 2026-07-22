import pytest
from rest_framework.test import APIClient

from agents.models import AgentDefinition
from agents.models.surface_models import Surface
from tables.models import Graph
from tables.models.graph_models import AgentNode, AgentNodeTask, TaskNode
from tables.models.rbac_models import Organization, OrganizationUser, Role
from tables.models.rbac_models.rbac_enums import BuiltInRole


@pytest.fixture
def role_member(db):
    return Role.objects.get(name=BuiltInRole.MEMBER, is_built_in=True, org__isnull=True)


@pytest.fixture
def org_a(db):
    return Organization.objects.create(name="Org A")


@pytest.fixture
def org_b(db):
    return Organization.objects.create(name="Org B")


@pytest.fixture
def member_a(db, django_user_model, org_a, role_member):
    user = django_user_model.objects.create_user(
        email="member_a@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=org_a, role=role_member)
    return user


@pytest.fixture
def client_a(member_a, org_a):
    client = APIClient()
    client.force_authenticate(user=member_a)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(org_a.id))
    return client


@pytest.mark.django_db
def test_tasknode_list_only_active_org(client_a, org_a, org_b):
    ga = Graph.objects.create(name="A", org=org_a)
    gb = Graph.objects.create(name="B", org=org_b)
    TaskNode.objects.create(graph=ga, node_name="ta")
    TaskNode.objects.create(graph=gb, node_name="tb")
    resp = client_a.get("/api/tasknodes/")
    assert resp.status_code == 200
    body = resp.data
    rows = body["results"] if isinstance(body, dict) and "results" in body else body
    names = {r["node_name"] for r in rows}
    assert "ta" in names and "tb" not in names


@pytest.mark.django_db
def test_tasknode_cross_org_detail_404(client_a, org_b):
    gb = Graph.objects.create(name="B", org=org_b)
    node = TaskNode.objects.create(graph=gb, node_name="tb")
    resp = client_a.get(f"/api/tasknodes/{node.id}/")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_agentnodetask_create_rejects_cross_org_parent(client_a, org_b):
    gb = Graph.objects.create(name="B", org=org_b)
    an = AgentNode.objects.create(graph=gb, node_name="an")
    resp = client_a.post(
        "/api/agentnodetasks/",
        {"agent_node": an.id, "name": "t", "order": 0, "instructions": "i"},
        format="json",
    )
    assert resp.status_code == 404


@pytest.mark.django_db
def test_tasknode_missing_org_header_400(member_a):
    client = APIClient()
    client.force_authenticate(user=member_a)
    resp = client.get("/api/tasknodes/")
    assert resp.status_code == 400


@pytest.mark.django_db
def test_tasknode_update_rejects_cross_org_reparent(client_a, org_a, org_b):
    ga = Graph.objects.create(name="A", org=org_a)
    gb = Graph.objects.create(name="B", org=org_b)
    node = TaskNode.objects.create(graph=ga, node_name="ta")
    resp = client_a.patch(f"/api/tasknodes/{node.id}/", {"graph": gb.id}, format="json")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_tasknode_update_same_org_field_succeeds(client_a, org_a):
    ga = Graph.objects.create(name="A", org=org_a)
    node = TaskNode.objects.create(graph=ga, node_name="ta")
    resp = client_a.patch(
        f"/api/tasknodes/{node.id}/", {"instructions": "updated"}, format="json"
    )
    assert resp.status_code == 200


@pytest.mark.django_db
def test_agentnode_update_rejects_cross_org_reparent(client_a, org_a, org_b):
    ga = Graph.objects.create(name="A", org=org_a)
    gb = Graph.objects.create(name="B", org=org_b)
    node = AgentNode.objects.create(graph=ga, node_name="aa")
    resp = client_a.patch(
        f"/api/agentnodes/{node.id}/", {"graph": gb.id}, format="json"
    )
    assert resp.status_code == 404


@pytest.mark.django_db
def test_agentnodetask_update_rejects_cross_org_reparent(client_a, org_a, org_b):
    ga = Graph.objects.create(name="A", org=org_a)
    gb = Graph.objects.create(name="B", org=org_b)
    agent_node_a = AgentNode.objects.create(graph=ga, node_name="aa")
    agent_node_b = AgentNode.objects.create(graph=gb, node_name="ab")
    task = AgentNodeTask.objects.create(agent_node=agent_node_a, name="t", order=0)
    resp = client_a.patch(
        f"/api/agentnodetasks/{task.id}/",
        {"agent_node": agent_node_b.id},
        format="json",
    )
    assert resp.status_code == 404


@pytest.mark.django_db
def test_surface_create_lands_in_active_org(client_a, org_a):
    resp = client_a.post("/api/surfaces/", {"name": "s1"}, format="json")
    assert resp.status_code == 201
    assert Surface.objects.get(id=resp.data["id"]).organization_id == org_a.id


@pytest.mark.django_db
def test_surface_list_only_active_org(client_a, org_a, org_b):
    Surface.objects.create(name="sa", organization=org_a)
    Surface.objects.create(name="sb", organization=org_b)
    resp = client_a.get("/api/surfaces/")
    assert resp.status_code == 200
    body = resp.data
    rows = body["results"] if isinstance(body, dict) and "results" in body else body
    names = {r["name"] for r in rows}
    assert "sa" in names and "sb" not in names


@pytest.mark.django_db
def test_surface_cross_org_detail_404(client_a, org_b):
    other = Surface.objects.create(name="sb", organization=org_b)
    resp = client_a.get(f"/api/surfaces/{other.id}/")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_surface_combine_excludes_other_org(client_a, org_a, org_b):
    sa = Surface.objects.create(name="sa", organization=org_a)
    sb = Surface.objects.create(name="sb", organization=org_b)
    resp = client_a.post(
        "/api/surfaces/combine/", {"surface_ids": [sa.id, sb.id]}, format="json"
    )
    # sb is outside the active org → validation rejects the unknown id.
    assert resp.status_code == 400


@pytest.mark.django_db
def test_agentdef_create_lands_in_active_org(client_a, org_a):
    resp = client_a.post("/api/agent-definitions/", {"name": "ad"}, format="json")
    assert resp.status_code == 201
    assert AgentDefinition.objects.get(id=resp.data["id"]).organization_id == org_a.id


@pytest.mark.django_db
def test_agentdef_cross_org_detail_404(client_a, org_b):
    other = AgentDefinition.objects.create(name="adb", organization=org_b)
    resp = client_a.get(f"/api/agent-definitions/{other.id}/")
    assert resp.status_code == 404
