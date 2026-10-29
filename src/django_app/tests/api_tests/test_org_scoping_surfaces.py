"""Org scoping of nodes, surfaces, agent definitions and realtime agent definitions:
each list shows only the active org, another org's row is a 404, and a write that
points at another org's object is refused."""

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
from rbac.models import Organization, OrganizationUser, Role
from rbac.models.enums import BuiltInRole
from tables.models.realtime_models import ElevenLabsRealtimeConfig, OpenAIRealtimeConfig, RealtimeAgentDefinition

pytestmark = pytest.mark.django_db


@pytest.fixture
def org_a(db):
    return Organization.objects.create(name="Org A")


@pytest.fixture
def org_b(db):
    return Organization.objects.create(name="Org B")


@pytest.fixture
def member_a(db, django_user_model, org_a):
    user = django_user_model.objects.create_user(email="member_a@example.com", password="StrongPass123!")
    role_member = Role.objects.get(name=BuiltInRole.MEMBER, is_built_in=True, org__isnull=True)
    OrganizationUser.objects.create(user=user, org=org_a, role=role_member)
    return user


@pytest.fixture
def client_a(member_a, org_a):
    client = APIClient()
    client.force_authenticate(user=member_a)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(org_a.id))
    return client


def _rows(resp):
    body = resp.data
    return body["results"] if isinstance(body, dict) and "results" in body else body


def _task_node(org, name):
    return TaskNode.objects.create(graph=Graph.objects.create(name=name, org=org), node_name=name)


def _realtime_agent(org, name):
    return RealtimeAgentDefinition.objects.create(agent_definition=AgentDefinition.objects.create(name=name, org=org))


# url, make(org, name), the response field that identifies a row, and the value it holds
LISTED = {
    "tasknodes": ("/api/tasknodes/", _task_node, "node_name", lambda obj: obj.node_name),
    "surfaces": ("/api/surfaces/", lambda org, name: Surface.objects.create(name=name, org=org), "name", lambda obj: obj.name),
    "realtime-agent-definitions": (
        "/api/realtime-agent-definitions/", _realtime_agent, "agent_definition", lambda obj: obj.agent_definition_id
    ),
}
DETAILED = {
    **LISTED,
    "agent-definitions": (
        "/api/agent-definitions/", lambda org, name: AgentDefinition.objects.create(name=name, org=org), "name", lambda obj: obj.name
    ),
}


@pytest.mark.parametrize("resource", list(LISTED))
def test_list_shows_only_the_active_org(client_a, org_a, org_b, resource):
    url, make, field, value = LISTED[resource]
    own, foreign = make(org_a, "a-row"), make(org_b, "b-row")

    resp = client_a.get(url)

    assert resp.status_code == 200
    shown = {row[field] for row in _rows(resp)}
    assert value(own) in shown
    assert value(foreign) not in shown


@pytest.mark.parametrize("resource", list(DETAILED))
def test_another_orgs_row_is_404(client_a, org_b, resource):
    url, make, _, _ = DETAILED[resource]

    assert client_a.get(f"{url}{make(org_b, 'b-row').pk}/").status_code == 404


@pytest.mark.parametrize(("url", "model"), [("/api/surfaces/", Surface), ("/api/agent-definitions/", AgentDefinition)])
def test_create_lands_in_the_active_org(client_a, org_a, url, model):
    resp = client_a.post(url, {"name": "new"}, format="json")

    assert resp.status_code == 201
    assert model.objects.get(id=resp.data["id"]).org_id == org_a.id


def test_request_without_org_header_is_400(member_a):
    client = APIClient()
    client.force_authenticate(user=member_a)

    assert client.get("/api/tasknodes/").status_code == 400


def _python_tool(org):
    return PythonCodeTool.objects.create(
        name="other-tool", description="t", python_code=PythonCode.objects.create(code="def main(): pass"), org=org
    )


# url, the field named in the error, and body(foreign_org, own_org)
FOREIGN_REFERENCES = {
    "agentdef-llm-config": ("/api/agent-definitions/", "llm_config", lambda b, a: {"name": "ad", "llm_config": LLMConfig.objects.create(org=b, custom_name="other").id}),
    "agentdef-fcm-llm-config": ("/api/agent-definitions/", "fcm_llm_config", lambda b, a: {"name": "ad", "fcm_llm_config": LLMConfig.objects.create(org=b, custom_name="other").id}),
    "agentdef-default-surface": ("/api/agent-definitions/", "default_surfaces", lambda b, a: {"name": "ad", "default_surfaces": [{"surface": Surface.objects.create(name="sb", org=b).id, "place": SurfacePlace.ALL}]}),
    "surface-owner-agent": ("/api/surfaces/", "owner_agent", lambda b, a: {"name": "s1", "owner_agent": AgentDefinition.objects.create(name="adb", org=b).id}),
    "surface-python-tool": ("/api/surfaces/", "python_tools", lambda b, a: {"name": "s1", "python_tools": [{"python_tool": _python_tool(b).id, "mode": "allow"}]}),
    "surface-mcp-tool": ("/api/surfaces/", "mcp_tools", lambda b, a: {"name": "s1", "mcp_tools": [{"mcp_tool": McpTool.objects.create(name="other-mcp", transport="http://example.com", tool_name="t", org=b).id, "mode": "allow"}]}),
    "surface-knowledge": ("/api/surfaces/", "knowledge", lambda b, a: {"name": "s1", "knowledge": [{"collection": SourceCollection.objects.create(org=b, collection_name="other").pk}]}),
    "realtime-openai-config": ("/api/realtime-agent-definitions/", "openai_config", lambda b, a: {"agent_definition": AgentDefinition.objects.create(name="ad", org=a).id, "openai_config": OpenAIRealtimeConfig.objects.create(custom_name="c", org=b).id}),
    "realtime-elevenlabs-config": ("/api/realtime-agent-definitions/", "elevenlabs_config", lambda b, a: {"agent_definition": AgentDefinition.objects.create(name="ad", org=a).id, "elevenlabs_config": ElevenLabsRealtimeConfig.objects.create(custom_name="c", org=b).id}),
    "realtime-agent-definition": ("/api/realtime-agent-definitions/", "agent_definition", lambda b, a: {"agent_definition": AgentDefinition.objects.create(name="adb", org=b).id}),
}


@pytest.mark.parametrize("case", list(FOREIGN_REFERENCES))
def test_create_pointing_at_another_orgs_object_is_400(client_a, org_a, org_b, case):
    url, field, body = FOREIGN_REFERENCES[case]
    resp = client_a.post(url, body(org_b, org_a), format="json")

    assert resp.status_code == 400
    assert field in resp.data["message"]
    assert not Surface.objects.filter(org=org_a).exists()
    assert not RealtimeAgentDefinition.objects.filter(agent_definition__org=org_a).exists()


def test_combining_another_orgs_surface_is_400(client_a, org_a, org_b):
    surfaces = [Surface.objects.create(name="sa", org=org_a).id, Surface.objects.create(name="sb", org=org_b).id]

    assert client_a.post("/api/surfaces/combine/", {"surface_ids": surfaces}, format="json").status_code == 400


@pytest.mark.parametrize("model", [TaskNode, AgentNode], ids=["tasknode", "agentnode"])
def test_moving_a_node_into_another_orgs_graph_is_400(client_a, org_a, org_b, model):
    node = model.objects.create(graph=Graph.objects.create(name="A", org=org_a), node_name="n")
    url = "/api/tasknodes/" if model is TaskNode else "/api/agentnodes/"

    resp = client_a.patch(f"{url}{node.id}/", {"graph": Graph.objects.create(name="B", org=org_b).id}, format="json")

    # `graph` is an OrgScopedPrimaryKeyRelatedField: a cross-org pk fails field validation.
    assert resp.status_code == 400
    assert "does not exist" in str(resp.data)
    node.refresh_from_db()
    assert node.graph.org_id == org_a.id


def test_a_same_org_node_update_succeeds(client_a, org_a):
    node = _task_node(org_a, "ta")

    assert client_a.patch(f"/api/tasknodes/{node.id}/", {"instructions": "updated"}, format="json").status_code == 200


def _agent_node(org, name):
    return AgentNode.objects.create(graph=Graph.objects.create(name=name, org=org), node_name=name)


def _task_write(client, write, own_node, task, payload):
    """POST a new task on `own_node`, or PATCH `task`, with `payload` merged in."""
    if write == "create":
        body = {"agent_node": own_node.id, "name": "new", "order": 7, "instructions": "i", **payload}
        return client.post("/api/agentnodetasks/", body, format="json")
    return client.patch(f"/api/agentnodetasks/{task.id}/", payload, format="json")


def _without_pk(resp, pk):
    return str(resp.data).replace(f'"{pk}"', '"<pk>"')


@pytest.mark.parametrize("write", ["create", "reparent"])
def test_an_agent_task_under_another_orgs_agent_node_looks_like_a_missing_one(client_a, org_a, org_b, write):
    foreign_node = _agent_node(org_b, "ab")
    own_node = _agent_node(org_a, "aa")
    task = AgentNodeTask.objects.create(agent_node=own_node, name="t", order=0)
    missing_pk = 2**31 - 1

    foreign = _task_write(client_a, write, own_node, task, {"agent_node": foreign_node.id})
    missing = _task_write(client_a, write, own_node, task, {"agent_node": missing_pk})

    assert foreign.status_code == missing.status_code == 400
    assert _without_pk(foreign, foreign_node.id) == _without_pk(missing, missing_pk)
    assert "does not exist" in str(foreign.data)
    task.refresh_from_db()
    assert task.agent_node_id == own_node.id
    assert not AgentNodeTask.objects.filter(agent_node=foreign_node).exists()


def test_filtering_tasks_by_another_orgs_agent_node_looks_like_a_missing_one(client_a, org_a, org_b):
    foreign_node = _agent_node(org_b, "ab")
    AgentNodeTask.objects.create(agent_node=foreign_node, name="f", order=0)
    own_node = _agent_node(org_a, "aa")
    own_task = AgentNodeTask.objects.create(agent_node=own_node, name="t", order=0)

    foreign = client_a.get(f"/api/agentnodetasks/?agent_node={foreign_node.id}")
    missing = client_a.get(f"/api/agentnodetasks/?agent_node={2**31 - 1}")
    own = client_a.get(f"/api/agentnodetasks/?agent_node={own_node.id}")

    assert foreign.status_code == missing.status_code == 200
    assert _rows(foreign) == _rows(missing) == []
    assert [row["id"] for row in _rows(own)] == [own_task.id]


@pytest.mark.parametrize("write", ["create", "update"])
def test_a_context_task_of_another_org_looks_like_a_missing_one(client_a, org_a, org_b, write):
    own_node = _agent_node(org_a, "aa")
    task = AgentNodeTask.objects.create(agent_node=own_node, name="t", order=5)
    foreign_task = AgentNodeTask.objects.create(agent_node=_agent_node(org_b, "ab"), name="f", order=0)
    missing_pk = 2**31 - 1

    foreign = _task_write(client_a, write, own_node, task, {"context_tasks": [foreign_task.id]})
    missing = _task_write(client_a, write, own_node, task, {"context_tasks": [missing_pk]})

    assert foreign.status_code == missing.status_code == 400
    assert _without_pk(foreign, foreign_task.id) == _without_pk(missing, missing_pk)
    assert "does not exist" in str(foreign.data)
    assert not task.context_tasks.exists()


@pytest.mark.parametrize("write", ["create", "update"])
def test_a_context_task_of_a_sibling_agent_node_in_the_same_org_is_still_rejected(client_a, org_a, write):
    own_node = _agent_node(org_a, "aa")
    task = AgentNodeTask.objects.create(agent_node=own_node, name="t", order=5)
    other_node_task = AgentNodeTask.objects.create(agent_node=_agent_node(org_a, "ab"), name="o", order=0)

    resp = _task_write(client_a, write, own_node, task, {"context_tasks": [other_node_task.id]})

    assert resp.status_code == 400
    assert "must belong to the same agent_node" in str(resp.data)


@pytest.mark.parametrize("write", ["create", "update"])
def test_an_earlier_task_of_the_same_agent_node_can_be_a_context_task(client_a, org_a, write):
    own_node = _agent_node(org_a, "aa")
    earlier = AgentNodeTask.objects.create(agent_node=own_node, name="e", order=0)
    task = AgentNodeTask.objects.create(agent_node=own_node, name="t", order=5)

    resp = _task_write(client_a, write, own_node, task, {"context_tasks": [earlier.id]})

    assert resp.status_code in (200, 201)
    assert resp.data["context_tasks"] == [earlier.id]
    assert resp.data["agent_node"] == own_node.id
    written = AgentNodeTask.objects.get(id=resp.data["id"])
    assert list(written.context_tasks.values_list("id", flat=True)) == [earlier.id]
