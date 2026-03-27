import pytest

from tables.models.graph_models import (
    CrewNode,
    DecisionTableNode,
    Edge,
    PythonNode,
)


@pytest.fixture
def python_node(graph, python_code) -> PythonNode:
    return PythonNode.objects.create(graph=graph, python_code=python_code)


@pytest.fixture
def crew_node(graph, crew) -> CrewNode:
    return CrewNode.objects.create(graph=graph, crew=crew)


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
