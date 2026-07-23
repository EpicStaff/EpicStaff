import pytest
from rest_framework.test import APIClient

from tables.models.crew_models import (
    Agent,
    AgentConfiguredTools,
    AgentMcpTools,
    AgentPythonCodeTools,
    Crew,
    Tool,
    ToolConfig,
)
from tables.models.graph_models import CrewNode, Graph
from tables.models.mcp_models import McpTool
from tables.models.python_models import PythonCode, PythonCodeTool
from tables.models.rbac_models import Organization, OrganizationUser, Role


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
def registered_tool() -> Tool:
    return Tool.objects.create(name="Wikipedia", name_alias="wikipedia", description="d")


@pytest.fixture
def used_graph_setup(org_a, registered_tool):
    """One agent using all 3 tool kinds, wired into a named graph via a
    named crew, so project/staff detail can be asserted by name."""
    tool_config = ToolConfig.objects.create(name="cfg1", tool=registered_tool)

    code = PythonCode.objects.create(code="def main(): return 1", entrypoint="main")
    python_tool = PythonCodeTool.objects.create(
        name="PyTool", description="d", python_code=code, org=org_a
    )

    mcp_tool = McpTool.objects.create(
        name="McpTool",
        transport="https://example.com/mcp",
        tool_name="do_thing",
        org=org_a,
    )

    agent = Agent.objects.create(
        role="Researcher", goal="goal", backstory="story", org=org_a
    )
    AgentConfiguredTools.objects.create(agent=agent, toolconfig=tool_config)
    AgentPythonCodeTools.objects.create(agent=agent, pythoncodetool=python_tool)
    AgentMcpTools.objects.create(agent=agent, mcptool=mcp_tool)

    crew = Crew.objects.create(name="crew1", org=org_a)
    crew.agents.set([agent])

    graph = Graph.objects.create(name="My Project", org=org_a)
    CrewNode.objects.create(crew=crew, graph=graph, node_name="crew_node1")

    return {
        "registered_tool": registered_tool,
        "python_tool": python_tool,
        "mcp_tool": mcp_tool,
        "agent": agent,
        "graph": graph,
    }


@pytest.fixture
def unused_python_tool(org_a) -> PythonCodeTool:
    code = PythonCode.objects.create(code="def main(): return 1", entrypoint="main")
    return PythonCodeTool.objects.create(
        name="UnusedTool", description="d", python_code=code, org=org_a
    )


# ---- tests ----


@pytest.mark.django_db
def test_configured_tool_detail_returns_project_and_staff(client_a, used_graph_setup):
    registered_tool = used_graph_setup["registered_tool"]
    agent = used_graph_setup["agent"]
    graph = used_graph_setup["graph"]

    resp = client_a.get(
        "/api/tools/usage-detail/",
        {"unique_name": f"configured-tool:{registered_tool.id}"},
    )
    assert resp.status_code == 200
    assert resp.data["projects"] == [{"id": graph.id, "name": graph.name}]
    assert resp.data["staff"] == [{"id": agent.id, "role": agent.role}]


@pytest.mark.django_db
def test_python_code_tool_detail_returns_project_and_staff(client_a, used_graph_setup):
    python_tool = used_graph_setup["python_tool"]
    agent = used_graph_setup["agent"]
    graph = used_graph_setup["graph"]

    resp = client_a.get(
        "/api/tools/usage-detail/",
        {"unique_name": f"python-code-tool:{python_tool.id}"},
    )
    assert resp.status_code == 200
    assert resp.data["projects"] == [{"id": graph.id, "name": graph.name}]
    assert resp.data["staff"] == [{"id": agent.id, "role": agent.role}]


@pytest.mark.django_db
def test_mcp_tool_detail_returns_project_and_staff(client_a, used_graph_setup):
    mcp_tool = used_graph_setup["mcp_tool"]
    agent = used_graph_setup["agent"]
    graph = used_graph_setup["graph"]

    resp = client_a.get(
        "/api/tools/usage-detail/",
        {"unique_name": f"mcp-tool:{mcp_tool.id}"},
    )
    assert resp.status_code == 200
    assert resp.data["projects"] == [{"id": graph.id, "name": graph.name}]
    assert resp.data["staff"] == [{"id": agent.id, "role": agent.role}]


@pytest.mark.django_db
def test_unused_tool_returns_empty_lists(client_a, unused_python_tool):
    resp = client_a.get(
        "/api/tools/usage-detail/",
        {"unique_name": f"python-code-tool:{unused_python_tool.id}"},
    )
    assert resp.status_code == 200
    assert resp.data == {"projects": [], "staff": []}


@pytest.mark.django_db
def test_missing_unique_name_is_400(client_a):
    resp = client_a.get("/api/tools/usage-detail/")
    assert resp.status_code == 400


@pytest.mark.django_db
def test_malformed_unique_name_is_400(client_a):
    resp = client_a.get(
        "/api/tools/usage-detail/", {"unique_name": "not-a-valid-name"}
    )
    assert resp.status_code == 400


@pytest.mark.django_db
def test_non_numeric_id_is_400(client_a):
    resp = client_a.get(
        "/api/tools/usage-detail/", {"unique_name": "configured-tool:abc"}
    )
    assert resp.status_code == 400


@pytest.mark.django_db
def test_unknown_prefix_is_400(client_a):
    resp = client_a.get(
        "/api/tools/usage-detail/", {"unique_name": "some-other-tool:1"}
    )
    assert resp.status_code == 400


@pytest.mark.django_db
def test_nonexistent_registered_tool_is_404(client_a):
    resp = client_a.get(
        "/api/tools/usage-detail/", {"unique_name": "configured-tool:999999"}
    )
    assert resp.status_code == 404


@pytest.mark.django_db
def test_cross_org_python_tool_is_404(client_a, org_b):
    code = PythonCode.objects.create(code="def main(): return 1", entrypoint="main")
    foreign_tool = PythonCodeTool.objects.create(
        name="ForeignTool", description="d", python_code=code, org=org_b
    )

    resp = client_a.get(
        "/api/tools/usage-detail/",
        {"unique_name": f"python-code-tool:{foreign_tool.id}"},
    )
    assert resp.status_code == 404


@pytest.mark.django_db
def test_built_in_python_code_tool_is_visible_not_404(client_a):
    # EST-3277: PythonCodeTool visibility is hybrid (built-in rows are
    # global, org_id=None) — a built-in tool must be resolvable in the
    # usage-detail lookup the same way it's listed in /api/tools/usage/,
    # not 404 just because it has no org.
    code = PythonCode.objects.create(code="def main(): return 1", entrypoint="main")
    builtin_tool = PythonCodeTool.objects.create(
        name="BuiltInTool", description="d", python_code=code, built_in=True, org=None
    )

    resp = client_a.get(
        "/api/tools/usage-detail/",
        {"unique_name": f"python-code-tool:{builtin_tool.id}"},
    )
    assert resp.status_code == 200
    assert resp.data == {"projects": [], "staff": []}


@pytest.mark.django_db
def test_cross_org_mcp_tool_is_404(client_a, org_b):
    foreign_tool = McpTool.objects.create(
        name="ForeignMcp",
        transport="https://example.com/mcp",
        tool_name="do_thing",
        org=org_b,
    )

    resp = client_a.get(
        "/api/tools/usage-detail/",
        {"unique_name": f"mcp-tool:{foreign_tool.id}"},
    )
    assert resp.status_code == 404


@pytest.mark.django_db
def test_requires_authentication(db):
    resp = APIClient().get(
        "/api/tools/usage-detail/", {"unique_name": "configured-tool:1"}
    )
    assert resp.status_code == 403
