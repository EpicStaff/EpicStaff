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
from tables.models.rbac_models import Organization, OrganizationUser, Role


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


@pytest.mark.django_db
def test_unused_tool_returns_empty_lists(client_a, unused_python_tool):
    resp = client_a.get(python_usage_detail_url(unused_python_tool.id))
    assert resp.status_code == 200
    assert resp.data == {"agents": [], "surfaces": []}


@pytest.mark.django_db
def test_nonexistent_python_code_tool_is_404(client_a):
    resp = client_a.get(python_usage_detail_url(999999))
    assert resp.status_code == 404


@pytest.mark.django_db
def test_nonexistent_mcp_tool_is_404(client_a):
    resp = client_a.get(mcp_usage_detail_url(999999))
    assert resp.status_code == 404


@pytest.mark.django_db
def test_non_numeric_python_code_tool_pk_is_404(client_a):
    resp = client_a.get(python_usage_detail_url("abc"))
    assert resp.status_code == 404


@pytest.mark.django_db
def test_cross_org_python_tool_is_404(client_a, org_b, python_tool_factory):
    foreign_tool = python_tool_factory(org_b, name="ForeignTool")

    resp = client_a.get(python_usage_detail_url(foreign_tool.id))
    assert resp.status_code == 404


@pytest.mark.django_db
def test_built_in_python_code_tool_is_visible_not_404(client_a, python_tool_factory):
    # PythonCodeTool visibility is hybrid (built-in rows are global,
    # org_id=None) — a built-in tool must be resolvable in the usage-detail
    # lookup the same way it's listed in the usage endpoint, not 404 just
    # because it has no org.
    builtin_tool = python_tool_factory(None, name="BuiltInTool", built_in=True)

    resp = client_a.get(python_usage_detail_url(builtin_tool.id))
    assert resp.status_code == 200
    assert resp.data == {"agents": [], "surfaces": []}


@pytest.mark.django_db
def test_cross_org_mcp_tool_is_404(client_a, org_b, mcp_tool_factory):
    foreign_tool = mcp_tool_factory(org_b, name="ForeignMcp")

    resp = client_a.get(mcp_usage_detail_url(foreign_tool.id))
    assert resp.status_code == 404


@pytest.mark.django_db
def test_non_numeric_mcp_tool_pk_is_404(client_a):
    resp = client_a.get(mcp_usage_detail_url("abc"))
    assert resp.status_code == 404


@pytest.mark.django_db
def test_requires_authentication(db):
    resp = APIClient().get(python_usage_detail_url(1))
    assert resp.status_code == 403


# ---- (a) agent reached via its own owned surface ----


@pytest.mark.django_db
def test_agent_reached_via_owned_surface(client_a, org_a, unused_python_tool):
    agent = AgentDefinition.objects.create(name="agent-owned", organization=org_a)
    surface = Surface.objects.create(
        name="s-owned", organization=org_a, owner_agent=agent
    )
    SurfacePythonTool.objects.create(
        surface=surface, python_tool=unused_python_tool, mode=ToolMode.ALLOW
    )

    resp = client_a.get(python_usage_detail_url(unused_python_tool.id))
    assert resp.status_code == 200
    assert resp.data["agents"] == [{"id": agent.id, "name": agent.name}]
    assert resp.data["surfaces"] == [
        {"id": surface.id, "name": surface.name, "kind": "surface"}
    ]


@pytest.mark.django_db
def test_agent_reached_via_owned_surface_mcp(client_a, org_a, unused_mcp_tool):
    agent = AgentDefinition.objects.create(name="agent-owned-mcp", organization=org_a)
    surface = Surface.objects.create(
        name="s-owned-mcp", organization=org_a, owner_agent=agent
    )
    SurfaceMcpTool.objects.create(
        surface=surface, mcp_tool=unused_mcp_tool, mode=ToolMode.ALLOW
    )

    resp = client_a.get(mcp_usage_detail_url(unused_mcp_tool.id))
    assert resp.status_code == 200
    assert resp.data["agents"] == [{"id": agent.id, "name": agent.name}]
    assert resp.data["surfaces"] == [
        {"id": surface.id, "name": surface.name, "kind": "surface"}
    ]


# ---- (b) agent reached via a shared surface assigned through AgentDefaultSurface ----


@pytest.mark.django_db
def test_agent_reached_via_shared_surface_assignment(
    client_a, org_a, unused_python_tool
):
    agent = AgentDefinition.objects.create(name="agent-shared", organization=org_a)
    surface = Surface.objects.create(name="s-shared", organization=org_a)
    SurfacePythonTool.objects.create(
        surface=surface, python_tool=unused_python_tool, mode=ToolMode.ALLOW
    )
    AgentDefaultSurface.objects.create(
        agent_definition=agent, surface=surface, place=SurfacePlace.ALL
    )

    resp = client_a.get(python_usage_detail_url(unused_python_tool.id))
    assert resp.status_code == 200
    assert resp.data["agents"] == [{"id": agent.id, "name": agent.name}]
    assert resp.data["surfaces"] == [
        {"id": surface.id, "name": surface.name, "kind": "surface"}
    ]


@pytest.mark.django_db
def test_agent_reachable_via_both_owned_and_shared_surface_not_double_counted(
    client_a, org_a, unused_python_tool
):
    """The SAME agent reachable via an owned surface AND via a separate
    shared surface assigned through AgentDefaultSurface, both carrying the
    tool, must appear exactly once in `agents`/`agents_count`."""
    agent = AgentDefinition.objects.create(name="agent-both", organization=org_a)

    owned_surface = Surface.objects.create(
        name="s-owned-both", organization=org_a, owner_agent=agent
    )
    SurfacePythonTool.objects.create(
        surface=owned_surface, python_tool=unused_python_tool, mode=ToolMode.ALLOW
    )

    shared_surface = Surface.objects.create(name="s-shared-both", organization=org_a)
    SurfacePythonTool.objects.create(
        surface=shared_surface, python_tool=unused_python_tool, mode=ToolMode.ALLOW
    )
    AgentDefaultSurface.objects.create(
        agent_definition=agent, surface=shared_surface, place=SurfacePlace.ALL
    )

    resp = client_a.get(python_usage_detail_url(unused_python_tool.id))
    assert resp.status_code == 200
    assert resp.data["agents"] == [{"id": agent.id, "name": agent.name}]
    surface_ids = {s["id"] for s in resp.data["surfaces"]}
    assert surface_ids == {owned_surface.id, shared_surface.id}


@pytest.mark.django_db
def test_agent_reached_via_task_node_surface_list_without_default_surface(
    client_a, org_a, unused_python_tool
):
    """A shared surface attached directly to a `TaskNode.surface_list` (no
    `AgentDefaultSurface` row at all) must still surface the node's
    `agent_definition` in `agents` — this is an independent reachability
    path used at runtime by `NodeSurfaceService.build_combined_surface`."""
    agent = AgentDefinition.objects.create(name="agent-node-surface", organization=org_a)
    surface = Surface.objects.create(name="s-node-list", organization=org_a)
    SurfacePythonTool.objects.create(
        surface=surface, python_tool=unused_python_tool, mode=ToolMode.ALLOW
    )

    graph = Graph.objects.create(name="Graph-node-list", org=org_a)
    task_node = TaskNode.objects.create(
        graph=graph, node_name="task_node_surface_list", agent_definition=agent
    )
    task_node.surface_list.add(surface)

    resp = client_a.get(python_usage_detail_url(unused_python_tool.id))
    assert resp.status_code == 200
    assert resp.data["agents"] == [{"id": agent.id, "name": agent.name}]


@pytest.mark.django_db
def test_agent_reached_via_agent_node_surface_list_without_default_surface(
    client_a, org_a, unused_python_tool
):
    """Same as the TaskNode case, for `AgentNode.surface_list`."""
    agent = AgentDefinition.objects.create(
        name="agent-node-surface-2", organization=org_a
    )
    surface = Surface.objects.create(name="s-node-list-2", organization=org_a)
    SurfacePythonTool.objects.create(
        surface=surface, python_tool=unused_python_tool, mode=ToolMode.ALLOW
    )

    graph = Graph.objects.create(name="Graph-node-list-2", org=org_a)
    agent_node = AgentNode.objects.create(
        graph=graph, node_name="agent_node_surface_list", agent_definition=agent
    )
    agent_node.surface_list.add(surface)

    resp = client_a.get(python_usage_detail_url(unused_python_tool.id))
    assert resp.status_code == 200
    assert resp.data["agents"] == [{"id": agent.id, "name": agent.name}]


@pytest.mark.django_db
def test_cross_org_task_node_surface_list_not_leaked(
    client_a, org_a, org_b, unused_python_tool
):
    """A TaskNode on a different org's Graph attaching (via the model layer,
    bypassing app-level validation) a shared surface for our org's tool must
    not surface an agent from the other org."""
    agent_b = AgentDefinition.objects.create(name="agent-b-node", organization=org_b)
    surface = Surface.objects.create(name="s-cross-org-node", organization=org_a)
    SurfacePythonTool.objects.create(
        surface=surface, python_tool=unused_python_tool, mode=ToolMode.ALLOW
    )

    graph_b = Graph.objects.create(name="Graph-b-node-list", org=org_b)
    task_node_b = TaskNode.objects.create(
        graph=graph_b, node_name="task_node_b_surface_list", agent_definition=agent_b
    )
    task_node_b.surface_list.add(surface)

    resp = client_a.get(python_usage_detail_url(unused_python_tool.id))
    assert resp.status_code == 200
    assert resp.data["agents"] == []


# ---- (c) / (d) flow_node surfaces from inline surfaces ----


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
    assert resp.data["agents"] == []
    assert resp.data["surfaces"] == [
        {
            "id": graph.id,
            "name": f"{graph.name} - {task_node.node_name}",
            "kind": "flow_node",
        }
    ]


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
    assert resp.data["agents"] == []
    assert resp.data["surfaces"] == [
        {
            "id": graph.id,
            "name": f"{graph.name} - {agent_node.node_name}",
            "kind": "flow_node",
        }
    ]


# ---- (e) mode="deny" never counts as usage ----


@pytest.mark.django_db
def test_deny_mode_catalog_surface_not_counted(client_a, org_a, unused_python_tool):
    agent = AgentDefinition.objects.create(name="agent-deny", organization=org_a)
    surface = Surface.objects.create(
        name="s-deny", organization=org_a, owner_agent=agent
    )
    SurfacePythonTool.objects.create(
        surface=surface, python_tool=unused_python_tool, mode=ToolMode.DENY
    )

    resp = client_a.get(python_usage_detail_url(unused_python_tool.id))
    assert resp.status_code == 200
    assert resp.data == {"agents": [], "surfaces": []}


@pytest.mark.django_db
def test_deny_mode_inline_surface_not_counted(client_a, org_a, unused_python_tool):
    graph = Graph.objects.create(name="Graph-deny", org=org_a)
    task_node = TaskNode.objects.create(graph=graph, node_name="task_node_deny")
    inline_surface = InlineSurface.objects.create(task_node=task_node)
    InlineSurfacePythonTool.objects.create(
        inline_surface=inline_surface,
        python_tool=unused_python_tool,
        mode=ToolMode.DENY,
    )

    resp = client_a.get(python_usage_detail_url(unused_python_tool.id))
    assert resp.status_code == 200
    assert resp.data == {"agents": [], "surfaces": []}


# ---- (f) org-scoping ----


@pytest.mark.django_db
def test_cross_org_surface_attachment_not_leaked(
    client_a, org_a, org_b, unused_python_tool
):
    """A Surface belonging to a DIFFERENT org that attaches
    `unused_python_tool` (same name as the surface, deliberately, to rule out
    name-based false negatives) must not surface its agent/surface entry —
    usage is scoped by `Surface.organization_id`, not by the tool's own org."""
    agent_b = AgentDefinition.objects.create(name="agent-b", organization=org_b)
    surface_b = Surface.objects.create(
        name="UnusedTool", organization=org_b, owner_agent=agent_b
    )
    SurfacePythonTool.objects.create(
        surface=surface_b, python_tool=unused_python_tool, mode=ToolMode.ALLOW
    )

    resp = client_a.get(python_usage_detail_url(unused_python_tool.id))
    assert resp.status_code == 200
    assert resp.data == {"agents": [], "surfaces": []}


@pytest.mark.django_db
def test_cross_org_flow_node_attachment_not_leaked(
    client_a, org_a, org_b, unused_python_tool
):
    """An InlineSurface owned by a TaskNode on a Graph belonging to a
    different org must not surface as a flow_node entry for a tool visible
    to the active org."""
    graph_b = Graph.objects.create(name="UnusedTool", org=org_b)
    task_node_b = TaskNode.objects.create(graph=graph_b, node_name="task_node_b")
    inline_surface_b = InlineSurface.objects.create(task_node=task_node_b)
    InlineSurfacePythonTool.objects.create(
        inline_surface=inline_surface_b,
        python_tool=unused_python_tool,
        mode=ToolMode.ALLOW,
    )

    resp = client_a.get(python_usage_detail_url(unused_python_tool.id))
    assert resp.status_code == 200
    assert resp.data == {"agents": [], "surfaces": []}
