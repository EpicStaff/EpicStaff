import pytest
from rest_framework.test import APIClient

from agents.models import AgentDefinition
from agents.models.agent_models import SurfacePlace
from agents.models.surface_models import Surface
from tables.models import Graph
from tables.models.graph_models import AgentNode, AgentNodeTask, StorageFile, TaskNode
from tables.models.knowledge_models.collection_models import SourceCollection
from tables.models.llm_models import LLMConfig
from tables.models.mcp_models import McpTool
from tables.models.python_models import PythonCode, PythonCodeTool
from tables.models.rbac_models import Organization, OrganizationUser, Role
from tables.models.rbac_models.rbac_enums import BuiltInRole
from tables.models.realtime_models import (
    ElevenLabsRealtimeConfig,
    OpenAIRealtimeConfig,
    RealtimeAgentDefinition,
)


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
    # `graph` is now an OrganizationScopedPrimaryKeyRelatedField, so a cross-org
    # pk is rejected at field validation (400) before the reparent guard runs.
    assert resp.status_code == 400
    assert "does not exist" in str(resp.data)


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
    # `graph` is now an OrganizationScopedPrimaryKeyRelatedField, so a cross-org
    # pk is rejected at field validation (400) before the reparent guard runs.
    assert resp.status_code == 400
    assert "does not exist" in str(resp.data)


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


@pytest.mark.django_db
def test_agentdef_llm_config_cross_org_rejected(client_a, org_b):
    other_llm_config = LLMConfig.objects.create(org=org_b, custom_name="other")
    resp = client_a.post(
        "/api/agent-definitions/",
        {"name": "ad", "llm_config": other_llm_config.id},
        format="json",
    )
    assert resp.status_code == 400
    assert "llm_config" in resp.data["message"]


@pytest.mark.django_db
def test_agentdef_fcm_llm_config_cross_org_rejected(client_a, org_b):
    other_llm_config = LLMConfig.objects.create(org=org_b, custom_name="other")
    resp = client_a.post(
        "/api/agent-definitions/",
        {"name": "ad", "fcm_llm_config": other_llm_config.id},
        format="json",
    )
    assert resp.status_code == 400
    assert "fcm_llm_config" in resp.data["message"]


@pytest.mark.django_db
def test_agentdef_default_surfaces_cross_org_surface_rejected(client_a, org_b):
    other_surface = Surface.objects.create(name="sb", organization=org_b)
    resp = client_a.post(
        "/api/agent-definitions/",
        {
            "name": "ad",
            "default_surfaces": [
                {"surface": other_surface.id, "place": SurfacePlace.ALL}
            ],
        },
        format="json",
    )
    assert resp.status_code == 400
    assert "default_surfaces" in resp.data["message"]


@pytest.mark.django_db
def test_surface_owner_agent_cross_org_rejected(client_a, org_b):
    other_agent_definition = AgentDefinition.objects.create(
        name="adb", organization=org_b
    )
    resp = client_a.post(
        "/api/surfaces/",
        {"name": "s1", "owner_agent": other_agent_definition.id},
        format="json",
    )
    assert resp.status_code == 400
    assert "owner_agent" in resp.data["message"]


@pytest.mark.django_db
def test_surface_python_tool_cross_org_rejected(client_a, org_b):
    code = PythonCode.objects.create(code="def main(): pass")
    other_tool = PythonCodeTool.objects.create(
        name="other-tool", description="t", python_code=code, org=org_b
    )
    resp = client_a.post(
        "/api/surfaces/",
        {
            "name": "s1",
            "python_tools": [{"python_tool": other_tool.id, "mode": "allow"}],
        },
        format="json",
    )
    assert resp.status_code == 400
    assert "python_tools" in resp.data["message"]


@pytest.mark.django_db
def test_surface_mcp_tool_cross_org_rejected(client_a, org_b):
    other_tool = McpTool.objects.create(
        name="other-mcp",
        transport="http://example.com",
        tool_name="t",
        org=org_b,
    )
    resp = client_a.post(
        "/api/surfaces/",
        {"name": "s1", "mcp_tools": [{"mcp_tool": other_tool.id, "mode": "allow"}]},
        format="json",
    )
    assert resp.status_code == 400
    assert "mcp_tools" in resp.data["message"]


@pytest.mark.django_db
def test_surface_storage_file_cross_org_rejected(client_a, org_b):
    other_file = StorageFile.objects.create(org=org_b, path="a.txt", name="a.txt")
    resp = client_a.post(
        "/api/surfaces/",
        {"name": "s1", "storage_items": [{"storage_file": other_file.id}]},
        format="json",
    )
    assert resp.status_code == 400
    assert "storage_items" in resp.data["message"]


@pytest.mark.django_db
def test_surface_knowledge_collection_cross_org_rejected(client_a, org_b):
    other_collection = SourceCollection.objects.create(
        org=org_b, collection_name="other-collection"
    )
    resp = client_a.post(
        "/api/surfaces/",
        {"name": "s1", "knowledge": [{"collection": other_collection.pk}]},
        format="json",
    )
    assert resp.status_code == 400
    assert "knowledge" in resp.data["message"]


@pytest.fixture
def openai_config_factory():
    def make(org):
        return OpenAIRealtimeConfig.objects.create(custom_name="c", org=org)

    return make


@pytest.fixture
def elevenlabs_config_factory():
    def make(org):
        return ElevenLabsRealtimeConfig.objects.create(custom_name="c", org=org)

    return make


@pytest.mark.django_db
def test_realtime_agent_definition_create_rejects_cross_org_openai_config(
    client_a, org_a, org_b, openai_config_factory
):
    agent_definition = AgentDefinition.objects.create(name="ad", organization=org_a)
    other_config = openai_config_factory(org_b)
    resp = client_a.post(
        "/api/realtime-agent-definitions/",
        {"agent_definition": agent_definition.id, "openai_config": other_config.id},
        format="json",
    )
    assert resp.status_code == 400
    assert "openai_config" in resp.data["message"]


@pytest.mark.django_db
def test_realtime_agent_definition_create_rejects_cross_org_elevenlabs_config(
    client_a, org_a, org_b, elevenlabs_config_factory
):
    agent_definition = AgentDefinition.objects.create(name="ad", organization=org_a)
    other_config = elevenlabs_config_factory(org_b)
    resp = client_a.post(
        "/api/realtime-agent-definitions/",
        {
            "agent_definition": agent_definition.id,
            "elevenlabs_config": other_config.id,
        },
        format="json",
    )
    assert resp.status_code == 400
    assert "elevenlabs_config" in resp.data["message"]


@pytest.mark.django_db
def test_realtime_agent_definition_create_rejects_cross_org_agent_definition(
    client_a, org_b
):
    other_agent_definition = AgentDefinition.objects.create(
        name="adb", organization=org_b
    )
    resp = client_a.post(
        "/api/realtime-agent-definitions/",
        {"agent_definition": other_agent_definition.id},
        format="json",
    )
    assert resp.status_code == 400
    assert "agent_definition" in resp.data["message"]


@pytest.mark.django_db
def test_realtime_agent_definition_viewset_cross_org_detail_404(client_a, org_b):
    other_agent_definition = AgentDefinition.objects.create(
        name="adb", organization=org_b
    )
    other_rt_agent_definition = RealtimeAgentDefinition.objects.create(
        agent_definition=other_agent_definition
    )
    resp = client_a.get(
        f"/api/realtime-agent-definitions/{other_rt_agent_definition.pk}/"
    )
    assert resp.status_code == 404


@pytest.mark.django_db
def test_realtime_agent_definition_viewset_list_only_active_org(client_a, org_a, org_b):
    agent_definition_a = AgentDefinition.objects.create(name="ada", organization=org_a)
    agent_definition_b = AgentDefinition.objects.create(name="adb", organization=org_b)
    RealtimeAgentDefinition.objects.create(agent_definition=agent_definition_a)
    RealtimeAgentDefinition.objects.create(agent_definition=agent_definition_b)

    resp = client_a.get("/api/realtime-agent-definitions/")

    assert resp.status_code == 200
    body = resp.data
    rows = body["results"] if isinstance(body, dict) and "results" in body else body
    ids = {row["agent_definition"] for row in rows}
    assert agent_definition_a.id in ids
    assert agent_definition_b.id not in ids
