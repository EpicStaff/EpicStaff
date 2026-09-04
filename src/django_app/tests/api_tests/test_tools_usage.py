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

PYTHON_USAGE_URL = "/api/python-code-tool/usage/"
MCP_USAGE_URL = "/api/mcp-tools/usage/"


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
def used_setup(org_a, python_tool_factory, mcp_tool_factory):
    """One agent reachable via its own owned surface carrying both tool
    kinds, so counts can be asserted for both `usage` endpoints."""
    python_tool = python_tool_factory(org_a, name="PyTool")
    mcp_tool = mcp_tool_factory(org_a, name="McpTool")

    agent = AgentDefinition.objects.create(name="agent1", organization=org_a)
    surface = Surface.objects.create(name="s1", organization=org_a, owner_agent=agent)
    SurfacePythonTool.objects.create(
        surface=surface, python_tool=python_tool, mode=ToolMode.ALLOW
    )
    SurfaceMcpTool.objects.create(
        surface=surface, mcp_tool=mcp_tool, mode=ToolMode.ALLOW
    )

    return {"python_tool": python_tool, "mcp_tool": mcp_tool, "agent": agent}


# ---- tests: python-code-tool / mcp-tool usage counts ----


@pytest.mark.django_db
def test_used_python_tool_has_correct_agents_and_surfaces_counts(
    client_a, used_setup
):
    resp = client_a.post(PYTHON_USAGE_URL)
    assert resp.status_code == 200
    rows = {row["id"]: row for row in resp.data}

    python_tool = used_setup["python_tool"]
    assert rows[python_tool.id] == {
        "id": python_tool.id,
        "agents_count": 1,
        "surfaces_count": 1,
        "is_built_in": False,
    }


@pytest.mark.django_db
def test_used_mcp_tool_has_correct_agents_and_surfaces_counts(client_a, used_setup):
    resp = client_a.post(MCP_USAGE_URL)
    assert resp.status_code == 200
    rows = {row["id"]: row for row in resp.data}

    mcp_tool = used_setup["mcp_tool"]
    assert rows[mcp_tool.id] == {
        "id": mcp_tool.id,
        "agents_count": 1,
        "surfaces_count": 1,
        "is_built_in": False,
    }


@pytest.mark.django_db
def test_unused_tool_has_zero_counts(client_a, unused_python_tool):
    resp = client_a.post(PYTHON_USAGE_URL)
    assert resp.status_code == 200
    rows = {row["id"]: row for row in resp.data}

    assert rows[unused_python_tool.id] == {
        "id": unused_python_tool.id,
        "agents_count": 0,
        "surfaces_count": 0,
        "is_built_in": False,
    }


@pytest.mark.django_db
def test_cross_org_python_tool_not_visible(client_a, org_b, python_tool_factory):
    foreign_tool = python_tool_factory(org_b, name="ForeignTool")

    resp = client_a.post(PYTHON_USAGE_URL)
    assert resp.status_code == 200
    ids = {row["id"] for row in resp.data}
    assert foreign_tool.id not in ids


@pytest.mark.django_db
def test_cross_org_mcp_tool_not_visible(client_a, org_b, mcp_tool_factory):
    foreign_tool = mcp_tool_factory(org_b, name="ForeignMcp")

    resp = client_a.post(MCP_USAGE_URL)
    assert resp.status_code == 200
    ids = {row["id"] for row in resp.data}
    assert foreign_tool.id not in ids


@pytest.mark.django_db
def test_requires_authentication(db):
    # Test settings zero out DEFAULT_AUTHENTICATION_CLASSES (the suite uses
    # force_authenticate instead), so with no authenticators configured DRF's
    # IsAuthenticated denies via PermissionDenied (403) rather than
    # NotAuthenticated (401) — matches the other plain-APIView endpoints in
    # this codebase (e.g. RunPythonCodeAPIView) under the same test settings.
    resp = APIClient().post(PYTHON_USAGE_URL)
    assert resp.status_code == 403


# ---- is_built_in field ----


@pytest.mark.django_db
def test_is_built_in_true_for_built_in_python_code_tool(client_a, python_tool_factory):
    tool = python_tool_factory(None, name="BuiltInPyTool", built_in=True)
    resp = client_a.post(PYTHON_USAGE_URL)
    assert resp.status_code == 200
    rows = {row["id"]: row for row in resp.data}
    assert rows[tool.id]["is_built_in"] is True


@pytest.mark.django_db
def test_is_built_in_false_for_non_built_in_python_code_tool(
    client_a, unused_python_tool
):
    resp = client_a.post(PYTHON_USAGE_URL)
    assert resp.status_code == 200
    rows = {row["id"]: row for row in resp.data}
    assert rows[unused_python_tool.id]["is_built_in"] is False


@pytest.mark.django_db
def test_is_built_in_false_for_mcp_tool(client_a, org_a, mcp_tool_factory):
    mcp_tool = mcp_tool_factory(org_a, name="McpToolStandalone")
    resp = client_a.post(MCP_USAGE_URL)
    assert resp.status_code == 200
    rows = {row["id"]: row for row in resp.data}
    assert rows[mcp_tool.id]["is_built_in"] is False


# ---- agent dedup across owned + shared-surface-assignment paths ----


@pytest.mark.django_db
def test_agent_reachable_via_both_paths_not_double_counted(
    client_a, org_a, unused_python_tool
):
    """An agent reachable via BOTH an owned surface AND a separate shared
    surface (assigned through AgentDefaultSurface), both carrying the tool,
    must be counted exactly once in `agents_count`. Two distinct surface
    attachments must still both count toward `surfaces_count`."""
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

    resp = client_a.post(PYTHON_USAGE_URL)
    assert resp.status_code == 200
    rows = {row["id"]: row for row in resp.data}
    row = rows[unused_python_tool.id]
    assert row["agents_count"] == 1
    assert row["surfaces_count"] == 2


# ---- agent reached via TaskNode/AgentNode.surface_list directly ----


@pytest.mark.django_db
def test_agent_counted_via_task_node_surface_list_without_default_surface(
    client_a, org_a, unused_python_tool
):
    """A shared surface attached directly to a `TaskNode.surface_list` (no
    `AgentDefaultSurface` row) must still count toward `agents_count` — an
    independent reachability path used at runtime by
    `NodeSurfaceService.build_combined_surface`."""
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

    resp = client_a.post(PYTHON_USAGE_URL)
    assert resp.status_code == 200
    rows = {row["id"]: row for row in resp.data}
    assert rows[unused_python_tool.id]["agents_count"] == 1


@pytest.mark.django_db
def test_agent_counted_via_agent_node_surface_list_without_default_surface(
    client_a, org_a, unused_python_tool
):
    """Same as the TaskNode case above, for `AgentNode.surface_list`."""
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

    resp = client_a.post(PYTHON_USAGE_URL)
    assert resp.status_code == 200
    rows = {row["id"]: row for row in resp.data}
    assert rows[unused_python_tool.id]["agents_count"] == 1


# ---- surfaces_count spans all three attachment families ----


@pytest.mark.django_db
def test_surfaces_count_spans_all_three_families(
    client_a, org_a, unused_python_tool
):
    surface = Surface.objects.create(name="s-family-catalog", organization=org_a)
    SurfacePythonTool.objects.create(
        surface=surface, python_tool=unused_python_tool, mode=ToolMode.ALLOW
    )

    graph = Graph.objects.create(name="graph-family", org=org_a)
    task_node = TaskNode.objects.create(graph=graph, node_name="task_node_family")
    inline_surface = InlineSurface.objects.create(task_node=task_node)
    InlineSurfacePythonTool.objects.create(
        inline_surface=inline_surface,
        python_tool=unused_python_tool,
        mode=ToolMode.ALLOW,
    )

    agent_node = AgentNode.objects.create(graph=graph, node_name="agent_node_family")
    agent_inline_surface = AgentInlineSurface.objects.create(agent_node=agent_node)
    AgentInlineSurfacePythonTool.objects.create(
        agent_inline_surface=agent_inline_surface,
        python_tool=unused_python_tool,
        mode=ToolMode.ALLOW,
    )

    resp = client_a.post(PYTHON_USAGE_URL)
    assert resp.status_code == 200
    rows = {row["id"]: row for row in resp.data}
    assert rows[unused_python_tool.id]["surfaces_count"] == 3


# ---- deny mode never counts ----


@pytest.mark.django_db
def test_deny_mode_row_not_counted(client_a, org_a, unused_python_tool):
    agent = AgentDefinition.objects.create(name="agent-deny", organization=org_a)
    surface = Surface.objects.create(
        name="s-deny", organization=org_a, owner_agent=agent
    )
    SurfacePythonTool.objects.create(
        surface=surface, python_tool=unused_python_tool, mode=ToolMode.DENY
    )

    resp = client_a.post(PYTHON_USAGE_URL)
    assert resp.status_code == 200
    rows = {row["id"]: row for row in resp.data}
    row = rows[unused_python_tool.id]
    assert row["agents_count"] == 0
    assert row["surfaces_count"] == 0


# ---- `ids` request-body filter ----


@pytest.mark.django_db
def test_ids_filter_returns_only_requested_rows(client_a, used_setup):
    python_tool = used_setup["python_tool"]

    resp = client_a.post(PYTHON_USAGE_URL, {"ids": [python_tool.id]}, format="json")
    assert resp.status_code == 200
    ids = {row["id"] for row in resp.data}
    assert ids == {python_tool.id}


@pytest.mark.django_db
def test_ids_omitted_preserves_full_list_behavior(client_a, used_setup):
    resp_no_ids = client_a.post(PYTHON_USAGE_URL)
    resp_with_ids_omitted = client_a.post(PYTHON_USAGE_URL, {}, format="json")
    assert resp_no_ids.status_code == 200
    assert resp_with_ids_omitted.status_code == 200
    assert {r["id"] for r in resp_no_ids.data} == {
        r["id"] for r in resp_with_ids_omitted.data
    }
    # sanity: at least one row present, not accidentally scoped
    assert len(resp_no_ids.data) >= 1


@pytest.mark.django_db
def test_ids_over_max_count_returns_400(client_a, monkeypatch):
    # MAX_USAGE_IDS is intentionally tied to api_settings.PAGE_SIZE (currently
    # 500000) — patch the mixin's class attribute directly rather than
    # building a request body with hundreds of thousands of ids.
    from tables.views.mixins import ToolUsageActionsMixin

    monkeypatch.setattr(ToolUsageActionsMixin, "MAX_USAGE_IDS", 200)
    too_many = list(range(1, 202))
    resp = client_a.post(MCP_USAGE_URL, {"ids": too_many}, format="json")
    assert resp.status_code == 400
    assert "maximum 200 allowed, got 201" in str(resp.data)


@pytest.mark.django_db
def test_ids_non_list_returns_400(client_a):
    resp = client_a.post(MCP_USAGE_URL, {"ids": "not-a-list"}, format="json")
    assert resp.status_code == 400


@pytest.mark.django_db
def test_ids_non_integer_entries_returns_400(client_a):
    resp = client_a.post(MCP_USAGE_URL, {"ids": ["abc"]}, format="json")
    assert resp.status_code == 400


@pytest.mark.django_db
def test_ids_for_foreign_org_tool_does_not_leak(client_a, org_b, python_tool_factory):
    """Requesting an `ids` entry for a tool from another org must not leak
    it — the row is simply absent from the response, same org-scoping as
    the unscoped list."""
    foreign_tool = python_tool_factory(org_b, name="ForeignTool")

    resp = client_a.post(
        PYTHON_USAGE_URL, {"ids": [foreign_tool.id]}, format="json"
    )
    assert resp.status_code == 200
    assert resp.data == []
