"""
Integration tests for TaskNodePayloadService.build_task_node_data.
"""

from __future__ import annotations

import pytest

from agents.models import AgentDefinition
from tables.models.graph_models import Graph, TaskNode
from tables.models.rbac_models import Organization
from tables.services.converter_service import ConverterService
from tables.services.task_node_payload_service import TaskNodePayloadService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def org(db):
    from tables.constants.organization_constants import DEFAULT_ORGANIZATION_NAME

    return Organization.objects.get_or_create(name=DEFAULT_ORGANIZATION_NAME)[0]


@pytest.fixture
def graph(db, org):
    return Graph.objects.create(name="task-node-payload-graph")


@pytest.fixture
def agent(db, org):
    return AgentDefinition.objects.create(
        organization=org,
        name="task-node-payload-agent",
        instructions="do things",
    )


@pytest.fixture
def task_node(db, graph, agent):
    return TaskNode.objects.create(
        graph=graph,
        node_name="task-node-1",
        agent_definition=agent,
        instructions="Summarize the findings.",
        output_variable_path="variables.result",
    )


# ---------------------------------------------------------------------------
# TaskNodePayloadService.build_task_node_data
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_build_task_node_data_includes_output_variable_path(task_node, agent):
    service = TaskNodePayloadService(ConverterService())

    data = service.build_task_node_data(
        task_node, node_name="task-node-1 #1", graph_id=None, session_id=None
    )

    assert data.node_name == "task-node-1 #1"
    assert data.agent_definition is not None
    assert data.agent_definition.id == agent.id
    assert data.instructions == "Summarize the findings."
    assert data.output_variable_path == "variables.result"


@pytest.mark.django_db
def test_build_task_node_data_without_output_variable_path_is_none(graph, agent):
    task_node = TaskNode.objects.create(
        graph=graph,
        node_name="task-node-no-output-path",
        agent_definition=agent,
        instructions="Summarize the findings.",
    )
    service = TaskNodePayloadService(ConverterService())

    data = service.build_task_node_data(
        task_node, node_name="task-node-no-output-path", graph_id=None, session_id=None
    )

    assert data.output_variable_path is None
