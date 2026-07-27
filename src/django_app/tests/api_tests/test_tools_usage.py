import pytest
from rest_framework.test import APIClient

from tables.models.crew_models import (
    Agent,
    AgentConfiguredTools,
    AgentMcpTools,
    AgentPythonCodeToolConfigs,
    AgentPythonCodeTools,
    Crew,
    Task,
    TaskConfiguredTools,
    TaskMcpTools,
    TaskPythonCodeToolConfigs,
    TaskPythonCodeTools,
    Tool,
    ToolConfig,
)
from tables.models.graph_models import CrewNode, Graph
from tables.models.mcp_models import McpTool
from tables.models.python_models import (
    PythonCode,
    PythonCodeTool,
    PythonCodeToolConfig,
)
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
    """One agent using all 3 tool kinds, member of a Crew (the FE "Project").
    The Crew is also wired into a Graph via a CrewNode to make sure the lower
    Graph orchestration layer has no bearing on `projects_count` (EST-3207
    follow-up: "projects" means Crew, not Graph)."""
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

    # Project/crew usage is derived from Task-level tool usage, not Agent
    # membership (EST-3207 design fix) — wire a Task per tool kind into the
    # Crew with the matching Task-tool join row.
    task = Task.objects.create(
        name="task1",
        crew=crew,
        instructions="do the thing",
        expected_output="result",
        order=1,
    )
    TaskConfiguredTools.objects.create(task=task, tool=tool_config)
    TaskPythonCodeTools.objects.create(task=task, tool=python_tool)
    TaskMcpTools.objects.create(task=task, tool=mcp_tool)

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
        "is_built_in": True,
    }
    assert rows[f"python-code-tool:{python_tool.id}"] == {
        "unique_name": f"python-code-tool:{python_tool.id}",
        "projects_count": 1,
        "staff_count": 1,
        "is_built_in": False,
    }
    assert rows[f"mcp-tool:{mcp_tool.id}"] == {
        "unique_name": f"mcp-tool:{mcp_tool.id}",
        "projects_count": 1,
        "staff_count": 1,
        "is_built_in": False,
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
        "is_built_in": False,
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
    inflate org_a's staff count, and an org_b Task using it must not inflate
    org_a's projects count."""
    tool_config = ToolConfig.objects.create(name="cfg-b", tool=registered_tool)
    foreign_agent = Agent.objects.create(
        role="agent", goal="goal", backstory="story", org=org_b
    )
    AgentConfiguredTools.objects.create(agent=foreign_agent, toolconfig=tool_config)

    foreign_crew = Crew.objects.create(name="crew-b", org=org_b)
    foreign_task = Task.objects.create(
        name="task-b",
        crew=foreign_crew,
        instructions="do it",
        expected_output="result",
        order=1,
    )
    TaskConfiguredTools.objects.create(task=foreign_task, tool=tool_config)

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


# ---- is_built_in field (EST-3277) ----


@pytest.mark.django_db
def test_is_built_in_true_for_built_in_python_code_tool(client_a):
    code = PythonCode.objects.create(code="def main(): return 1", entrypoint="main")
    tool = PythonCodeTool.objects.create(
        name="BuiltInPyTool",
        description="d",
        python_code=code,
        built_in=True,
        org=None,
    )
    resp = client_a.get("/api/tools/usage/")
    assert resp.status_code == 200
    rows = {row["unique_name"]: row for row in resp.data}
    assert rows[f"python-code-tool:{tool.id}"]["is_built_in"] is True


@pytest.mark.django_db
def test_is_built_in_false_for_non_built_in_python_code_tool(
    client_a, unused_python_tool
):
    resp = client_a.get("/api/tools/usage/")
    assert resp.status_code == 200
    rows = {row["unique_name"]: row for row in resp.data}
    key = f"python-code-tool:{unused_python_tool.id}"
    assert rows[key]["is_built_in"] is False


@pytest.mark.django_db
def test_is_built_in_true_for_registered_tool(client_a, registered_tool):
    resp = client_a.get("/api/tools/usage/")
    assert resp.status_code == 200
    rows = {row["unique_name"]: row for row in resp.data}
    assert rows[f"configured-tool:{registered_tool.id}"]["is_built_in"] is True


@pytest.mark.django_db
def test_is_built_in_false_for_mcp_tool(client_a, org_a):
    mcp_tool = McpTool.objects.create(
        name="McpToolStandalone",
        transport="https://example.com/mcp",
        tool_name="do_thing",
        org=org_a,
    )
    resp = client_a.get("/api/tools/usage/")
    assert resp.status_code == 200
    rows = {row["unique_name"]: row for row in resp.data}
    assert rows[f"mcp-tool:{mcp_tool.id}"]["is_built_in"] is False


# ---- python-code-tool config join path (Major #3) ----


@pytest.mark.django_db
def test_python_tool_agent_reachable_only_via_config_path_is_counted(
    client_a, org_a, unused_python_tool
):
    """An agent (staff) that only holds a `PythonCodeToolConfig` for the tool
    (no direct `AgentPythonCodeTools` row) must still be counted — exercising
    the `AgentPythonCodeToolConfigs -> PythonCodeToolConfig.tool` indirect
    join path in `_python_tool_agents_by_tool`. A Task on the same Crew,
    reachable only via the equivalent `TaskPythonCodeToolConfigs` path, must
    likewise count for `projects_count` (`_python_tool_tasks_by_tool`)."""
    tool_config = PythonCodeToolConfig.objects.create(
        name="cfg1", tool=unused_python_tool, org=org_a
    )
    agent = Agent.objects.create(
        role="ConfigOnlyAgent", goal="goal", backstory="story", org=org_a
    )
    AgentPythonCodeToolConfigs.objects.create(
        agent=agent, pythoncodetoolconfig=tool_config
    )

    crew = Crew.objects.create(name="crew-config-only", org=org_a)
    crew.agents.set([agent])
    graph = Graph.objects.create(name="graph-config-only", org=org_a)
    CrewNode.objects.create(crew=crew, graph=graph, node_name="crew_node1")

    task = Task.objects.create(
        name="task-config-only",
        crew=crew,
        instructions="do it",
        expected_output="result",
        order=1,
    )
    TaskPythonCodeToolConfigs.objects.create(task=task, tool=tool_config)

    resp = client_a.get("/api/tools/usage/")
    assert resp.status_code == 200
    rows = {row["unique_name"]: row for row in resp.data}
    key = f"python-code-tool:{unused_python_tool.id}"
    assert rows[key]["staff_count"] == 1
    assert rows[key]["projects_count"] == 1


@pytest.mark.django_db
def test_python_tool_agent_reachable_via_both_paths_not_double_counted(
    client_a, org_a, unused_python_tool
):
    """An agent reachable via BOTH the direct `AgentPythonCodeTools` row AND
    a `PythonCodeToolConfig` for the same tool must be counted exactly once —
    `_merge_pairs_by_tool` must dedupe by agent id, not double-count. A Task
    on the same Crew reachable via both the direct `TaskPythonCodeTools` row
    AND `TaskPythonCodeToolConfigs` for the same tool must likewise count as
    exactly ONE crew for `projects_count`, not two/zero."""
    tool_config = PythonCodeToolConfig.objects.create(
        name="cfg1", tool=unused_python_tool, org=org_a
    )
    agent = Agent.objects.create(
        role="BothPathsAgent", goal="goal", backstory="story", org=org_a
    )
    AgentPythonCodeTools.objects.create(
        agent=agent, pythoncodetool=unused_python_tool
    )
    AgentPythonCodeToolConfigs.objects.create(
        agent=agent, pythoncodetoolconfig=tool_config
    )

    crew = Crew.objects.create(name="crew-both-paths", org=org_a)
    crew.agents.set([agent])
    graph = Graph.objects.create(name="graph-both-paths", org=org_a)
    CrewNode.objects.create(crew=crew, graph=graph, node_name="crew_node1")

    task = Task.objects.create(
        name="task-both-paths",
        crew=crew,
        instructions="do it",
        expected_output="result",
        order=1,
    )
    TaskPythonCodeTools.objects.create(task=task, tool=unused_python_tool)
    TaskPythonCodeToolConfigs.objects.create(task=task, tool=tool_config)

    resp = client_a.get("/api/tools/usage/")
    assert resp.status_code == 200
    rows = {row["unique_name"]: row for row in resp.data}
    key = f"python-code-tool:{unused_python_tool.id}"
    assert rows[key]["staff_count"] == 1
    assert rows[key]["projects_count"] == 1


# ---- "projects" means Crew (reached via Task), not Graph (EST-3207 follow-up) ----


@pytest.mark.django_db
def test_project_counted_via_task_without_any_graph(
    client_a, org_a, unused_python_tool
):
    """A Crew never wired into any Graph (no CrewNode), reached via a Task
    that uses the tool, must still count as a "project" — Task-level tool
    usage within a Crew is what "projects_count" means (not Agent membership,
    and not the lower Graph orchestration layer)."""
    crew = Crew.objects.create(name="crew-no-graph", org=org_a)
    task = Task.objects.create(
        name="task-no-graph",
        crew=crew,
        instructions="do it",
        expected_output="result",
        order=1,
    )
    TaskPythonCodeTools.objects.create(task=task, tool=unused_python_tool)

    resp = client_a.get("/api/tools/usage/")
    assert resp.status_code == 200
    rows = {row["unique_name"]: row for row in resp.data}
    key = f"python-code-tool:{unused_python_tool.id}"
    assert rows[key]["staff_count"] == 0
    assert rows[key]["projects_count"] == 1


@pytest.mark.django_db
def test_projects_count_reflects_crews_not_graphs(
    client_a, org_a, unused_python_tool
):
    """One Crew wired into TWO Graphs (two CrewNodes), reached via a Task
    that uses the tool, must still count as ONE project — before the fix,
    counting distinct Graph ids here would have (incorrectly) reported 2."""
    crew = Crew.objects.create(name="crew-multi-graph", org=org_a)
    task = Task.objects.create(
        name="task-multi-graph",
        crew=crew,
        instructions="do it",
        expected_output="result",
        order=1,
    )
    TaskPythonCodeTools.objects.create(task=task, tool=unused_python_tool)

    graph1 = Graph.objects.create(name="graph1", org=org_a)
    graph2 = Graph.objects.create(name="graph2", org=org_a)
    CrewNode.objects.create(crew=crew, graph=graph1, node_name="crew_node1")
    CrewNode.objects.create(crew=crew, graph=graph2, node_name="crew_node2")

    resp = client_a.get("/api/tools/usage/")
    assert resp.status_code == 200
    rows = {row["unique_name"]: row for row in resp.data}
    key = f"python-code-tool:{unused_python_tool.id}"
    assert rows[key]["staff_count"] == 0
    assert rows[key]["projects_count"] == 1


# ---- projects_count no longer follows from Agent/Crew membership alone
# (EST-3207 design fix — the bug this change fixes) ----


@pytest.mark.django_db
def test_agent_in_crew_using_tool_does_not_count_project_without_task_usage(
    client_a, org_a, unused_python_tool
):
    """An agent IS a member of a Crew and DOES use the tool directly, but NO
    Task in that Crew uses the tool. `staff_count` must still reflect the
    agent (Agent-level join, unchanged), but `projects_count` must be 0 —
    project/crew usage is derived from Task-level tool usage, not from Agent
    membership. This is the core bug this change fixes: before the fix,
    `projects_count` was trivially correlated with `staff_count` because both
    were derived from the same Agent->Crew join."""
    agent = Agent.objects.create(
        role="MemberOnlyAgent", goal="goal", backstory="story", org=org_a
    )
    AgentPythonCodeTools.objects.create(agent=agent, pythoncodetool=unused_python_tool)

    crew = Crew.objects.create(name="crew-member-only", org=org_a)
    crew.agents.set([agent])

    # A Task exists on the Crew, but it does NOT reference the tool at all.
    Task.objects.create(
        name="unrelated-task",
        crew=crew,
        instructions="do something else",
        expected_output="result",
        order=1,
    )

    resp = client_a.get("/api/tools/usage/")
    assert resp.status_code == 200
    rows = {row["unique_name"]: row for row in resp.data}
    key = f"python-code-tool:{unused_python_tool.id}"
    assert rows[key]["staff_count"] == 1
    assert rows[key]["projects_count"] == 0
