import pytest

from tables.constants.organization_constants import DEFAULT_ORGANIZATION_NAME
from agents.models import AgentDefinition, Surface
from tables.models.graph_models import (
    CrewNode,
    DecisionTableNode,
    Edge,
    PythonNode,
    StartNode,
    TaskNode,
)
from tables.models.mcp_models import McpTool
from tables.models.python_models import PythonCode, PythonCodeTool
from tables.models.rbac_models import Organization


@pytest.fixture
def python_node(graph, python_code) -> PythonNode:
    return PythonNode.objects.create(graph=graph, python_code=python_code)


@pytest.fixture
def crew_node(graph, crew) -> CrewNode:
    return CrewNode.objects.create(graph=graph, crew=crew)


@pytest.fixture
def start_node(graph) -> StartNode:
    return StartNode.objects.create(graph=graph, variables={})


@pytest.fixture
def decision_table_node(graph) -> DecisionTableNode:
    return DecisionTableNode.objects.create(graph=graph, node_name="dt_node_1")


@pytest.fixture
def edge(graph, python_node, crew_node) -> Edge:
    return Edge.objects.create(
        graph=graph,
        start_node_id=python_node.id,
        end_node_id=crew_node.id,
    )


@pytest.fixture
def task_node(graph) -> TaskNode:
    return TaskNode.objects.create(graph=graph, node_name="task_node_1")


@pytest.fixture
def bulk_save_org(db) -> Organization:
    """Organization matching the bulk-save service's org resolution
    (Organization.objects.get(name=DEFAULT_ORGANIZATION_NAME)). Named
    distinctly from the top-level `default_org` fixture (used by `auth_client`
    for RBAC), which creates an unrelated Organization named "Default
    Organization"."""
    return Organization.objects.get_or_create(name=DEFAULT_ORGANIZATION_NAME)[0]


@pytest.fixture
def other_org(db) -> Organization:
    return Organization.objects.create(name="bulk-save-other-org")


@pytest.fixture
def shared_surface(bulk_save_org) -> Surface:
    return Surface.objects.create(
        organization=bulk_save_org,
        name="bulk-save-shared-surface",
        owner_agent=None,
    )


@pytest.fixture
def other_org_surface(other_org) -> Surface:
    return Surface.objects.create(
        organization=other_org,
        name="bulk-save-other-org-surface",
        owner_agent=None,
    )


@pytest.fixture
def agent_definition(bulk_save_org) -> AgentDefinition:
    return AgentDefinition.objects.create(
        organization=bulk_save_org,
        name="bulk-save-agent",
        instructions="do things",
    )


@pytest.fixture
def agent_owned_surface(bulk_save_org, agent_definition) -> Surface:
    return Surface.objects.create(
        organization=bulk_save_org,
        name="bulk-save-agent-owned-surface",
        owner_agent=agent_definition,
    )


@pytest.fixture
def py_tool(db) -> PythonCodeTool:
    code = PythonCode.objects.create(code="def main(): pass")
    return PythonCodeTool.objects.create(
        name="bulk-save-py-tool",
        description="test",
        python_code=code,
    )


@pytest.fixture
def mcp_tool(db) -> McpTool:
    return McpTool.objects.create(
        name="bulk-save-mcp-tool",
        transport="http://localhost/sse",
        tool_name="bulk_save_tool",
    )
