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
    """One agent using all 3 tool kinds, wired into a graph via a crew node."""
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
        role="agent", goal="goal", backstory="story", org=org_a
    )
    AgentConfiguredTools.objects.create(agent=agent, toolconfig=tool_config)
    AgentPythonCodeTools.objects.create(agent=agent, pythoncodetool=python_tool)
    AgentMcpTools.objects.create(agent=agent, mcptool=mcp_tool)

    crew = Crew.objects.create(name="crew1", org=org_a)
    crew.agents.set([agent])

    graph = Graph.objects.create(name="graph1", org=org_a)
    CrewNode.objects.create(crew=crew, graph=graph, node_name="crew_node1")

    return {
        "registered_tool": registered_tool,
        "python_tool": python_tool,
        "mcp_tool": mcp_tool,
    }


@pytest.fixture
def unused_python_tool(org_a) -> PythonCodeTool:
    code = PythonCode.objects.create(code="def main(): return 1", entrypoint="main")
    return PythonCodeTool.objects.create(
        name="UnusedTool", description="d", python_code=code, org=org_a
    )


# ---- tests ----


@pytest.mark.django_db
def test_used_tools_have_correct_projects_and_staff_counts(client_a, used_graph_setup):
    resp = client_a.get("/api/tools/usage/")
    assert resp.status_code == 200
    rows = {row["unique_name"]: row for row in resp.data}

    registered_tool = used_graph_setup["registered_tool"]
    python_tool = used_graph_setup["python_tool"]
    mcp_tool = used_graph_setup["mcp_tool"]

    assert rows[f"configured-tool:{registered_tool.id}"] == {
        "unique_name": f"configured-tool:{registered_tool.id}",
        "projects_count": 1,
        "staff_count": 1,
    }
    assert rows[f"python-code-tool:{python_tool.id}"] == {
        "unique_name": f"python-code-tool:{python_tool.id}",
        "projects_count": 1,
        "staff_count": 1,
    }
    assert rows[f"mcp-tool:{mcp_tool.id}"] == {
        "unique_name": f"mcp-tool:{mcp_tool.id}",
        "projects_count": 1,
        "staff_count": 1,
    }


@pytest.mark.django_db
def test_unused_tool_has_zero_counts(client_a, unused_python_tool):
    resp = client_a.get("/api/tools/usage/")
    assert resp.status_code == 200
    rows = {row["unique_name"]: row for row in resp.data}

    key = f"python-code-tool:{unused_python_tool.id}"
    assert rows[key] == {
        "unique_name": key,
        "projects_count": 0,
        "staff_count": 0,
    }


@pytest.mark.django_db
def test_registered_tool_always_included_even_with_no_org_scope(
    client_a, registered_tool
):
    resp = client_a.get("/api/tools/usage/")
    assert resp.status_code == 200
    rows = {row["unique_name"]: row for row in resp.data}
    assert f"configured-tool:{registered_tool.id}" in rows


@pytest.mark.django_db
def test_cross_org_python_tool_not_visible(client_a, org_b):
    code = PythonCode.objects.create(code="def main(): return 1", entrypoint="main")
    foreign_tool = PythonCodeTool.objects.create(
        name="ForeignTool", description="d", python_code=code, org=org_b
    )

    resp = client_a.get("/api/tools/usage/")
    assert resp.status_code == 200
    unique_names = {row["unique_name"] for row in resp.data}
    assert f"python-code-tool:{foreign_tool.id}" not in unique_names


@pytest.mark.django_db
def test_cross_org_mcp_tool_not_visible(client_a, org_b):
    foreign_tool = McpTool.objects.create(
        name="ForeignMcp",
        transport="https://example.com/mcp",
        tool_name="do_thing",
        org=org_b,
    )

    resp = client_a.get("/api/tools/usage/")
    assert resp.status_code == 200
    unique_names = {row["unique_name"] for row in resp.data}
    assert f"mcp-tool:{foreign_tool.id}" not in unique_names


@pytest.mark.django_db
def test_cross_org_agent_usage_not_counted_for_shared_registered_tool(
    client_a, org_b, registered_tool
):
    """A registered Tool is global, but an org_b agent using it must not
    inflate org_a's staff/projects counts."""
    tool_config = ToolConfig.objects.create(name="cfg-b", tool=registered_tool)
    foreign_agent = Agent.objects.create(
        role="agent", goal="goal", backstory="story", org=org_b
    )
    AgentConfiguredTools.objects.create(agent=foreign_agent, toolconfig=tool_config)

    resp = client_a.get("/api/tools/usage/")
    assert resp.status_code == 200
    rows = {row["unique_name"]: row for row in resp.data}
    assert rows[f"configured-tool:{registered_tool.id}"]["staff_count"] == 0
    assert rows[f"configured-tool:{registered_tool.id}"]["projects_count"] == 0


@pytest.mark.django_db
def test_requires_authentication(db):
    # Test settings zero out DEFAULT_AUTHENTICATION_CLASSES (the suite uses
    # force_authenticate instead), so with no authenticators configured DRF's
    # IsAuthenticated denies via PermissionDenied (403) rather than
    # NotAuthenticated (401) — matches the other plain-APIView endpoints in
    # this codebase (e.g. RunPythonCodeAPIView) under the same test settings.
    resp = APIClient().get("/api/tools/usage/")
    assert resp.status_code == 403
