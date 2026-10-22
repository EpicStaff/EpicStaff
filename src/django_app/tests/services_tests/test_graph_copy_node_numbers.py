"""A copied flow numbers its nodes 1..K in the source's order; the source keeps its numbers."""

import pytest

from tables.models import AgentNode, Graph, GraphNote, PythonCode, PythonNode, StartNode
from tables.services.copy_services.graph_copy_service import GraphCopyService
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403


def _python_node(graph, node_name, node_number):
    code = PythonCode.objects.create(code="def main(): ...", entrypoint="main")
    return PythonNode.objects.create(
        graph=graph, node_name=node_name, python_code=code, node_number=node_number
    )


def _numbers_by_name(graph):
    return {
        **dict(graph.agent_node_list.values_list("node_name", "node_number")),
        **dict(graph.python_node_list.values_list("node_name", "node_number")),
    }


@pytest.fixture
def source_flow(acme):
    """#2 is an agent node and #7 a python node: the python table is copied first,
    so a copy that numbered nodes in table order would get the order wrong."""
    graph = Graph.objects.create(name="Source Flow", org=acme)
    StartNode.objects.create(graph=graph, variables={})
    GraphNote.objects.create(graph=graph, content="unnumbered note")
    AgentNode.objects.create(graph=graph, node_name="second", node_number=2)
    _python_node(graph, "seventh", 7)
    graph.refresh_from_db()
    return graph


@pytest.mark.django_db
def test_copy_numbers_nodes_one_to_k_in_source_order(source_flow):
    copied = GraphCopyService().copy(source_flow)

    copied.refresh_from_db()
    assert _numbers_by_name(copied) == {"second": 1, "seventh": 2}
    assert copied.node_number_seq == 2


@pytest.mark.django_db
def test_copy_leaves_the_source_numbers_and_counter_unchanged(source_flow):
    GraphCopyService().copy(source_flow)

    source_flow.refresh_from_db()
    assert _numbers_by_name(source_flow) == {"second": 2, "seventh": 7}
    assert source_flow.node_number_seq == 7


@pytest.mark.django_db
def test_node_added_to_a_copy_continues_from_k(source_flow):
    copied = GraphCopyService().copy(source_flow)

    assert AgentNode.objects.create(graph=copied, node_name="added").node_number == 3
