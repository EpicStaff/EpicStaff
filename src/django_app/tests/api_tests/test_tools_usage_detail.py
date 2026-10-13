import pytest
from rest_framework.test import APIClient

from agents.models import (
    AgentDefaultSurface,
    AgentDefinition,
    AgentInlineSurface,
    AgentInlineSurfacePythonTool,
    InlineSurface,
    InlineSurfacePythonTool,
    Surface,
    SurfaceMcpTool,
    SurfacePlace,
    SurfacePythonTool,
    ToolMode,
)
from tables.models.graph_models import AgentNode, Graph, TaskNode
from tables.models.mcp_models import McpTool
from tables.models.python_models import PythonCode, PythonCodeTool
from rbac.models import Organization, OrganizationUser, Role


def python_usage_detail_url(tool_id) -> str:
    return f"/api/python-code-tool/{tool_id}/usage-detail/"


def mcp_usage_detail_url(tool_id) -> str:
    return f"/api/mcp-tools/{tool_id}/usage-detail/"


# ---- fixtures ----


@pytest.fixture
def org_admin_role(db):
    return Role.objects.get(name="Org Admin", is_built_in=True, org__isnull=True)


@pytest.fixture
def org_a(db):
    return Organization.objects.create(name="Org A")


@pytest.fixture
def org_b(db):
    return Organization.objects.create(name="Org B")


@pytest.fixture
def member_a(db, django_user_model, org_a, org_admin_role):
    user = django_user_model.objects.create_user(
        email="member_a@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=org_a, role=org_admin_role)
    return user


@pytest.fixture
def client_a(member_a, org_a):
    client = APIClient()
    client.force_authenticate(user=member_a)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(org_a.id))
    return client


@pytest.fixture
def python_tool_factory():
    def make(org, name="PyTool", built_in=False):
        code = PythonCode.objects.create(code="def main(): return 1", entrypoint="main")
        return PythonCodeTool.objects.create(
            name=name, description="d", python_code=code, org=org, built_in=built_in
        )

    return make


@pytest.fixture
def mcp_tool_factory():
    def make(org, name="McpTool"):
        return McpTool.objects.create(
            name=name,
            transport="https://example.com/mcp",
            tool_name="do_thing",
            org=org,
        )

    return make


@pytest.fixture
def unused_python_tool(org_a, python_tool_factory) -> PythonCodeTool:
    return python_tool_factory(org_a, name="UnusedTool")


@pytest.fixture
def unused_mcp_tool(org_a, mcp_tool_factory) -> McpTool:
    return mcp_tool_factory(org_a, name="UnusedMcpTool")


# ---- tests: unused / not-found / auth (unchanged shape) ----


def _empty_buckets() -> dict:
    return {"agent_surface": [], "shared_surface": [], "inline_surface": []}


def _attach_on_own_agent_surface(org_a, org_b, tool, mode):
    agent = AgentDefinition.objects.create(name="agent-deny", org=org_a)
    surface = Surface.objects.create(name="s-deny", org=org_a, owner_agent=agent)
    SurfacePythonTool.objects.create(surface=surface, python_tool=tool, mode=mode)


def _attach_on_own_task_node(org_a, org_b, tool, mode):
    task_node = TaskNode.objects.create(graph=Graph.objects.create(name="Graph-deny", org=org_a), node_name="task_node_deny")
    InlineSurfacePythonTool.objects.create(
        inline_surface=InlineSurface.objects.create(task_node=task_node), python_tool=tool, mode=mode
    )


def _attach_on_other_orgs_surface(org_a, org_b, tool, mode):
    # Same name as the tool, to rule out name-based false negatives: usage is scoped by Surface.org_id.
    agent_b = AgentDefinition.objects.create(name="agent-b", org=org_b)
    surface_b = Surface.objects.create(name="UnusedTool", org=org_b, owner_agent=agent_b)
    SurfacePythonTool.objects.create(surface=surface_b, python_tool=tool, mode=mode)


def _attach_on_other_orgs_task_node(org_a, org_b, tool, mode):
    task_node_b = TaskNode.objects.create(graph=Graph.objects.create(name="UnusedTool", org=org_b), node_name="task_node_b")
    InlineSurfacePythonTool.objects.create(
        inline_surface=InlineSurface.objects.create(task_node=task_node_b), python_tool=tool, mode=mode
    )


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("built_in", "attach", "mode"),
    [
        (False, None, None),
        # Built-in tools have no org but are visible, so they resolve rather than 404.
        (True, None, None),
        (False, _attach_on_own_agent_surface, ToolMode.DENY),
        (False, _attach_on_own_task_node, ToolMode.DENY),
        (False, _attach_on_other_orgs_surface, ToolMode.ALLOW),
        (False, _attach_on_other_orgs_task_node, ToolMode.ALLOW),
    ],
    ids=["unused", "built-in", "deny-on-surface", "deny-inline", "other-orgs-surface", "other-orgs-flow-node"],
)
def test_tool_without_visible_allow_usage_has_empty_buckets(
    client_a, org_a, org_b, python_tool_factory, built_in, attach, mode
):
    tool = python_tool_factory(None if built_in else org_a, name="UnusedTool", built_in=built_in)
    if attach is not None:
        attach(org_a, org_b, tool, mode)

    resp = client_a.get(python_usage_detail_url(tool.id))

    assert resp.status_code == 200
    assert resp.data == _empty_buckets()


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("detail_url", "factory"),
    [(python_usage_detail_url, "python_tool_factory"), (mcp_usage_detail_url, "mcp_tool_factory")],
    ids=["python", "mcp"],
)
@pytest.mark.parametrize("pk", ["missing", "non-numeric", "other-org"])
def test_tool_outside_the_org_is_404(request, client_a, org_b, detail_url, factory, pk):
    if pk == "other-org":
        pk = request.getfixturevalue(factory)(org_b, name="ForeignTool").id
    elif pk == "missing":
        pk = 999999
    else:
        pk = "abc"

    assert client_a.get(detail_url(pk)).status_code == 404


@pytest.mark.django_db
def test_requires_authentication(db):
    resp = APIClient().get(python_usage_detail_url(1))
    assert resp.status_code == 401


# ---- agent_surface: catalog Surface with owner_agent set ----


@pytest.mark.django_db
def test_surface_entry_agent_specific(client_a, org_a, unused_python_tool):
    agent = AgentDefinition.objects.create(name="agent-owned", org=org_a)
    surface = Surface.objects.create(
        name="s-owned", org=org_a, owner_agent=agent
    )
    SurfacePythonTool.objects.create(
        surface=surface, python_tool=unused_python_tool, mode=ToolMode.ALLOW
    )

    resp = client_a.get(python_usage_detail_url(unused_python_tool.id))
    assert resp.status_code == 200
    assert resp.data["agent_surface"] == [
        {"id": surface.id, "name": surface.name, "node_id": None}
    ]
    assert resp.data["shared_surface"] == []
    assert resp.data["inline_surface"] == []


@pytest.mark.django_db
def test_surface_entry_agent_specific_mcp(client_a, org_a, unused_mcp_tool):
    agent = AgentDefinition.objects.create(name="agent-owned-mcp", org=org_a)
    surface = Surface.objects.create(
        name="s-owned-mcp", org=org_a, owner_agent=agent
    )
    SurfaceMcpTool.objects.create(
        surface=surface, mcp_tool=unused_mcp_tool, mode=ToolMode.ALLOW
    )

    resp = client_a.get(mcp_usage_detail_url(unused_mcp_tool.id))
    assert resp.status_code == 200
    assert resp.data["agent_surface"] == [
        {"id": surface.id, "name": surface.name, "node_id": None}
    ]
    assert resp.data["shared_surface"] == []
    assert resp.data["inline_surface"] == []


# ---- shared_surface: catalog Surface with owner_agent null ----


@pytest.mark.django_db
def test_surface_entry_shared_regardless_of_agent_default_surface_assignment(
    client_a, org_a, unused_python_tool
):
    """A shared surface (`owner_agent` null) lands in `shared_surface`
    whether or not it's assigned to any agent via `AgentDefaultSurface` —
    that assignment no longer affects which bucket it lands in."""
    surface = Surface.objects.create(name="s-shared", org=org_a)
    SurfacePythonTool.objects.create(
        surface=surface, python_tool=unused_python_tool, mode=ToolMode.ALLOW
    )
    agent = AgentDefinition.objects.create(name="agent-shared", org=org_a)
    AgentDefaultSurface.objects.create(
        agent_definition=agent, surface=surface, place=SurfacePlace.ALL
    )

    resp = client_a.get(python_usage_detail_url(unused_python_tool.id))
    assert resp.status_code == 200
    assert resp.data["shared_surface"] == [
        {"id": surface.id, "name": surface.name, "node_id": None}
    ]
    assert resp.data["agent_surface"] == []
    assert resp.data["inline_surface"] == []


@pytest.mark.django_db
def test_surface_entry_shared_without_any_agent_assignment(
    client_a, org_a, unused_python_tool
):
    surface = Surface.objects.create(name="s-shared-unassigned", org=org_a)
    SurfacePythonTool.objects.create(
        surface=surface, python_tool=unused_python_tool, mode=ToolMode.ALLOW
    )

    resp = client_a.get(python_usage_detail_url(unused_python_tool.id))
    assert resp.status_code == 200
    assert resp.data["shared_surface"] == [
        {"id": surface.id, "name": surface.name, "node_id": None}
    ]
    assert resp.data["agent_surface"] == []
    assert resp.data["inline_surface"] == []


# ---- inline_surface: InlineSurface / AgentInlineSurface ----


@pytest.mark.django_db
def test_surface_entry_from_task_node_inline_surface(
    client_a, org_a, unused_python_tool
):
    graph = Graph.objects.create(name="Graph1", org=org_a)
    task_node = TaskNode.objects.create(graph=graph, node_name="task_node_1")
    inline_surface = InlineSurface.objects.create(task_node=task_node)
    InlineSurfacePythonTool.objects.create(
        inline_surface=inline_surface,
        python_tool=unused_python_tool,
        mode=ToolMode.ALLOW,
    )

    resp = client_a.get(python_usage_detail_url(unused_python_tool.id))
    assert resp.status_code == 200
    assert resp.data["inline_surface"] == [
        {
            "id": graph.id,
            "name": f"{graph.name} - {task_node.node_name}",
            "node_id": task_node.id,
        }
    ]
    assert resp.data["agent_surface"] == []
    assert resp.data["shared_surface"] == []


@pytest.mark.django_db
def test_surface_entry_from_agent_node_inline_surface(
    client_a, org_a, unused_python_tool
):
    graph = Graph.objects.create(name="Graph2", org=org_a)
    agent_node = AgentNode.objects.create(graph=graph, node_name="agent_node_1")
    inline_surface = AgentInlineSurface.objects.create(agent_node=agent_node)
    AgentInlineSurfacePythonTool.objects.create(
        agent_inline_surface=inline_surface,
        python_tool=unused_python_tool,
        mode=ToolMode.ALLOW,
    )

    resp = client_a.get(python_usage_detail_url(unused_python_tool.id))
    assert resp.status_code == 200
    assert resp.data["inline_surface"] == [
        {
            "id": graph.id,
            "name": f"{graph.name} - {agent_node.node_name}",
            "node_id": agent_node.id,
        }
    ]
    assert resp.data["agent_surface"] == []
    assert resp.data["shared_surface"] == []


@pytest.mark.django_db
def test_inline_entries_from_two_nodes_in_same_graph_share_id_but_differ_by_node_id(
    client_a, org_a, unused_python_tool
):
    """Two different nodes in the same graph both attaching the same tool
    inline produce two `inline_surface` entries with the same `id` (the graph is the
    navigation target) — `node_id` is what actually distinguishes them."""
    graph = Graph.objects.create(name="Graph-collision", org=org_a)

    task_node = TaskNode.objects.create(graph=graph, node_name="task_node_x")
    inline_surface = InlineSurface.objects.create(task_node=task_node)
    InlineSurfacePythonTool.objects.create(
        inline_surface=inline_surface,
        python_tool=unused_python_tool,
        mode=ToolMode.ALLOW,
    )

    agent_node = AgentNode.objects.create(graph=graph, node_name="agent_node_x")
    agent_inline_surface = AgentInlineSurface.objects.create(agent_node=agent_node)
    AgentInlineSurfacePythonTool.objects.create(
        agent_inline_surface=agent_inline_surface,
        python_tool=unused_python_tool,
        mode=ToolMode.ALLOW,
    )

    resp = client_a.get(python_usage_detail_url(unused_python_tool.id))
    assert resp.status_code == 200
    entries = resp.data["inline_surface"]
    assert len(entries) == 2
    assert {e["id"] for e in entries} == {graph.id}
    assert {e["node_id"] for e in entries} == {task_node.id, agent_node.id}


# ---- mode="deny" never counts as usage ----


# ---- org-scoping ----


