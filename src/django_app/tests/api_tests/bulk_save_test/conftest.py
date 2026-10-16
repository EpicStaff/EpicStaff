import pytest

from agents.models import AgentDefinition, Surface
from tables.models.graph_models import (
    DecisionTableNode,
    Edge,
    PythonNode,
    StartNode,
    TaskNode,
)
from tables.models.mcp_models import McpTool
from tables.models.python_models import PythonCode, PythonCodeTool
from rbac.models import Organization


@pytest.fixture
def python_node(graph, python_code) -> PythonNode:
    return PythonNode.objects.create(graph=graph, python_code=python_code)


@pytest.fixture
def start_node(graph) -> StartNode:
    return StartNode.objects.create(graph=graph, variables={})


@pytest.fixture
def decision_table_node(graph) -> DecisionTableNode:
    return DecisionTableNode.objects.create(graph=graph, node_name="dt_node_1")


@pytest.fixture
def edge(graph, start_node, python_node) -> Edge:
    return Edge.objects.create(
        graph=graph,
        start_node_id=start_node.id,
        end_node_id=python_node.id,
    )


@pytest.fixture
def task_node(graph) -> TaskNode:
    return TaskNode.objects.create(graph=graph, node_name="task_node_1")


@pytest.fixture
def other_org(db) -> Organization:
    return Organization.objects.create(name="bulk-save-other-org")


@pytest.fixture
def shared_surface(default_org) -> Surface:
    return Surface.objects.create(
        org=default_org,
        name="bulk-save-shared-surface",
        owner_agent=None,
    )


@pytest.fixture
def other_org_surface(other_org) -> Surface:
    return Surface.objects.create(
        org=other_org,
        name="bulk-save-other-org-surface",
        owner_agent=None,
    )


@pytest.fixture
def agent_definition(default_org) -> AgentDefinition:
    return AgentDefinition.objects.create(
        org=default_org,
        name="bulk-save-agent",
        instruction_list=[{"name": "Instruction_1.md", "content": "do things"}],
    )


@pytest.fixture
def agent_owned_surface(default_org, agent_definition) -> Surface:
    return Surface.objects.create(
        org=default_org,
        name="bulk-save-agent-owned-surface",
        owner_agent=agent_definition,
    )


@pytest.fixture
def py_tool(default_org) -> PythonCodeTool:
    code = PythonCode.objects.create(code="def main(): pass")
    return PythonCodeTool.objects.create(
        name="bulk-save-py-tool",
        description="test",
        python_code=code,
        org=default_org,
    )


@pytest.fixture
def mcp_tool(default_org) -> McpTool:
    return McpTool.objects.create(
        name="bulk-save-mcp-tool",
        transport="http://localhost/sse",
        tool_name="bulk_save_tool",
        org=default_org,
    )
