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
    """One agent-owned surface carrying both tool kinds, so counts can be
    asserted for both `usage` endpoints."""
    python_tool = python_tool_factory(org_a, name="PyTool")
    mcp_tool = mcp_tool_factory(org_a, name="McpTool")

    agent = AgentDefinition.objects.create(name="agent1", org=org_a)
    surface = Surface.objects.create(name="s1", org=org_a, owner_agent=agent)
    SurfacePythonTool.objects.create(
        surface=surface, python_tool=python_tool, mode=ToolMode.ALLOW
    )
    SurfaceMcpTool.objects.create(
        surface=surface, mcp_tool=mcp_tool, mode=ToolMode.ALLOW
    )

    return {"python_tool": python_tool, "mcp_tool": mcp_tool, "agent": agent}


# ---- tests: python-code-tool / mcp-tool usage counts ----


@pytest.mark.django_db
@pytest.mark.parametrize(("url", "tool_key"), [(PYTHON_USAGE_URL, "python_tool"), (MCP_USAGE_URL, "mcp_tool")], ids=["python", "mcp"])
def test_used_tool_has_correct_surface_counts(client_a, used_setup, url, tool_key):
    resp = client_a.post(url)

    assert resp.status_code == 200
    tool = used_setup[tool_key]
    assert {row["id"]: row for row in resp.data}[tool.id] == {
        "id": tool.id,
        "agent_surface_count": 1,
        "shared_surface_count": 0,
        "inline_surface_count": 0,
        "is_built_in": False,
    }


@pytest.mark.django_db
@pytest.mark.parametrize("denied_on_a_surface", [False, True], ids=["unused", "deny-mode-only"])
def test_tool_not_allowed_anywhere_has_zero_counts(client_a, org_a, unused_python_tool, denied_on_a_surface):
    if denied_on_a_surface:
        agent = AgentDefinition.objects.create(name="agent-deny", org=org_a)
        surface = Surface.objects.create(name="s-deny", org=org_a, owner_agent=agent)
        SurfacePythonTool.objects.create(surface=surface, python_tool=unused_python_tool, mode=ToolMode.DENY)

    resp = client_a.post(PYTHON_USAGE_URL)

    assert resp.status_code == 200
    assert {row["id"]: row for row in resp.data}[unused_python_tool.id] == {
        "id": unused_python_tool.id,
        "agent_surface_count": 0,
        "shared_surface_count": 0,
        "inline_surface_count": 0,
        "is_built_in": False,
    }


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("url", "make_foreign"),
    [(PYTHON_USAGE_URL, "python_tool_factory"), (MCP_USAGE_URL, "mcp_tool_factory")],
    ids=["python", "mcp"],
)
@pytest.mark.parametrize("asked_by_id", [False, True], ids=["listed", "asked-by-id"])
def test_another_orgs_tool_never_appears(request, client_a, org_b, url, make_foreign, asked_by_id):
    foreign_tool = request.getfixturevalue(make_foreign)(org_b, name="ForeignTool")

    resp = client_a.post(url, {"ids": [foreign_tool.id]} if asked_by_id else {}, format="json")

    assert resp.status_code == 200
    assert foreign_tool.id not in {row["id"] for row in resp.data}


@pytest.mark.django_db
def test_requires_authentication(db):
    # Test settings use JwtOrApiKeyAuthentication, whose authenticate_header
    # makes DRF answer an anonymous request with 401 rather than 403.
    resp = APIClient().post(PYTHON_USAGE_URL)
    assert resp.status_code == 401


# ---- is_built_in field ----


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("url", "make_tool", "expected"),
    [
        (PYTHON_USAGE_URL, lambda f, org: f("python_tool_factory")(None, name="BuiltInPyTool", built_in=True), True),
        (PYTHON_USAGE_URL, lambda f, org: f("python_tool_factory")(org, name="OrgPyTool"), False),
        (MCP_USAGE_URL, lambda f, org: f("mcp_tool_factory")(org, name="McpToolStandalone"), False),
    ],
    ids=["built-in-python", "org-python", "mcp"],
)
def test_is_built_in_flag(request, client_a, org_a, url, make_tool, expected):
    tool = make_tool(request.getfixturevalue, org_a)

    resp = client_a.post(url)

    assert resp.status_code == 200
    assert {row["id"]: row for row in resp.data}[tool.id]["is_built_in"] is expected


# ---- counts span all three attachment families ----


@pytest.mark.django_db
def test_counts_span_all_three_families(
    client_a, org_a, unused_python_tool
):
    surface = Surface.objects.create(name="s-family-catalog", org=org_a)
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
    row = rows[unused_python_tool.id]
    # catalog surface (shared, owner_agent null) -> shared_surface_count
    assert row["shared_surface_count"] == 1
    assert row["agent_surface_count"] == 0
    # task-node inline + agent-node inline both collapse into inline_surface_count
    assert row["inline_surface_count"] == 2


# ---- deny mode never counts ----


# ---- `ids` request-body filter ----


@pytest.mark.django_db
def test_ids_filter_returns_only_requested_rows(client_a, used_setup):
    python_tool = used_setup["python_tool"]

    resp = client_a.post(PYTHON_USAGE_URL, {"ids": [python_tool.id]}, format="json")
    assert resp.status_code == 200
    ids = {row["id"] for row in resp.data}
    assert ids == {python_tool.id}


@pytest.mark.django_db
@pytest.mark.parametrize("body", [{}, {"ids": []}], ids=["ids-omitted", "ids-empty"])
def test_omitted_or_empty_ids_return_every_visible_row(client_a, used_setup, body):
    everything = {row["id"] for row in client_a.post(PYTHON_USAGE_URL).data}

    resp = client_a.post(PYTHON_USAGE_URL, body, format="json")

    assert resp.status_code == 200
    assert {row["id"] for row in resp.data} == everything
    assert used_setup["python_tool"].id in everything


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("cap", "body", "message"),
    [
        # Over the cap without ids: refused rather than silently truncated.
        (0, None, "ids"),
        (200, {"ids": list(range(1, 202))}, "maximum 200 allowed, got 201"),
        (None, {"ids": "not-a-list"}, None),
        # bool is an int subclass: [true] would otherwise pass as tool id 1.
        (None, {"ids": [True]}, None),
        (None, {"ids": ["abc"]}, None),
    ],
    ids=["over-cap-without-ids", "too-many-ids", "ids-not-a-list", "ids-bool", "ids-not-integers"],
)
def test_invalid_ids_request_is_400(client_a, used_setup, monkeypatch, cap, body, message):
    from tables.views.mixins import ToolUsageActionsMixin

    if cap is not None:
        # MAX_USAGE_IDS is tied to api_settings.PAGE_SIZE (500000); lower it instead of sending that many ids.
        monkeypatch.setattr(ToolUsageActionsMixin, "MAX_USAGE_IDS", cap)

    resp = client_a.post(MCP_USAGE_URL, body, format="json") if body is not None else client_a.post(PYTHON_USAGE_URL)

    assert resp.status_code == 400
    if message is not None:
        assert message in str(resp.data)


# ---- bucket classification: agent_surface vs shared_surface ----


@pytest.mark.django_db
def test_agent_specific_surface_and_unrelated_shared_surface_both_count(
    client_a, org_a, unused_python_tool
):
    """An agent-specific surface (`owner_agent` set) counts toward
    `agent_surface_count`, and a shared surface (`owner_agent` null, whether
    or not it's assigned to any agent via `AgentDefaultSurface`) counts
    toward `shared_surface_count` — the FE doesn't need agent-reachability
    distinctions here, only the per-bucket totals."""
    agent = AgentDefinition.objects.create(name="agent-specific", org=org_a)
    owned_surface = Surface.objects.create(
        name="s-owned", org=org_a, owner_agent=agent
    )
    SurfacePythonTool.objects.create(
        surface=owned_surface, python_tool=unused_python_tool, mode=ToolMode.ALLOW
    )

    shared_surface = Surface.objects.create(name="s-shared", org=org_a)
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
    assert row["agent_surface_count"] == 1
    assert row["shared_surface_count"] == 1
    assert row["inline_surface_count"] == 0
