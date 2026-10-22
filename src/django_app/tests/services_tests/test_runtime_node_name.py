"""Runtime node names carry the node's "#N" badge ahead of its id.

The runtime name ("Name #N #id", or "Name #id" for a node without a number) is
the LangGraph node key, the edge start/end key, the decision-table route
target, the session entrypoint and the session message name. Every builder
must produce the same string for the same node, or the crew runtime cannot
route between them.
"""

import pytest

from tables.models import Edge, EndNode, StartNode
from tables.models.graph_models import (
    AgentNode,
    ConditionGroup,
    DecisionTableNode,
    Graph,
    PythonNode,
)
from tables.models.python_models import PythonCode
from tables.services.session_manager_service import SessionManagerService
from utils.graph_utils import (
    NodeNameResolver,
    node_label,
    runtime_node_name,
)


def _python_node(graph: Graph, node_name: str, node_number: int) -> PythonNode:
    return PythonNode.objects.create(
        graph=graph,
        node_name=node_name,
        node_number=node_number,
        python_code=PythonCode.objects.create(code="def main(): return 1"),
    )


@pytest.mark.parametrize(
    ("node_name", "node_number", "expected"),
    [
        ("Python", 3, "Python #3"),
        ("Python", None, "Python"),
        ("Python", 0, "Python #0"),
        ("Name with #hash", 12, "Name with #hash #12"),
    ],
)
def test_node_label(node_name, node_number, expected):
    assert node_label(node_name=node_name, node_number=node_number) == expected


@pytest.mark.parametrize(
    ("node_name", "node_number", "node_id", "expected"),
    [
        ("Python", 3, 12345, "Python #3 #12345"),
        ("Python", None, 12345, "Python #12345"),
        ("__end_node__", None, 7, "__end_node__ #7"),
    ],
)
def test_runtime_node_name(node_name, node_number, node_id, expected):
    assert (
        runtime_node_name(node_name=node_name, node_number=node_number, node_id=node_id)
        == expected
    )


@pytest.mark.django_db
def test_unscoped_resolver_includes_the_node_number(graph):
    node = _python_node(graph, "Py", node_number=3)

    assert NodeNameResolver()(node.id) == f"Py #3 #{node.id}"


@pytest.mark.django_db
def test_session_graph_data_uses_numbered_runtime_names_in_lockstep(graph):
    start_node = StartNode.objects.create(graph=graph, variables={})
    python_node = _python_node(graph, "Py", node_number=3)
    agent_node = AgentNode.objects.create(graph=graph, node_name="Writer", node_number=5)
    target_node = _python_node(graph, "Target", node_number=8)
    end_node = EndNode.objects.create(graph=graph, output_map={"context": "variables"})
    decision_table = DecisionTableNode.objects.create(
        graph=graph,
        node_name="Router",
        node_number=4,
        default_next_node_id=target_node.id,
        next_error_node_id=end_node.id,
    )
    ConditionGroup.objects.create(
        decision_table_node=decision_table,
        group_name="group",
        group_type="simple",
        order=0,
        next_node_id=agent_node.id,
    )
    Edge.objects.create(graph=graph, start_node_id=start_node.id, end_node_id=python_node.id)
    Edge.objects.create(graph=graph, start_node_id=python_node.id, end_node_id=decision_table.id)
    Edge.objects.create(graph=graph, start_node_id=agent_node.id, end_node_id=end_node.id)

    graph_data = SessionManagerService()._build_graph_data(
        graph, None, None, start_node=start_node
    )

    python_name = f"Py #3 #{python_node.id}"
    agent_name = f"Writer #5 #{agent_node.id}"
    router_name = f"Router #4 #{decision_table.id}"
    target_name = f"Target #8 #{target_node.id}"
    end_name = f"__end_node__ #{end_node.id}"
    assert graph_data.entrypoint == python_name
    assert {node.node_name for node in graph_data.python_node_list} == {python_name, target_name}
    assert [node.node_name for node in graph_data.agent_node_list] == [agent_name]
    [router_data] = graph_data.decision_table_node_list
    assert router_data.node_name == router_name
    assert router_data.default_next_node == target_name
    assert router_data.next_error_node == end_name
    assert router_data.conditional_group_list[0].next_node == agent_name
    assert graph_data.end_node.node_name == end_name
    assert {(edge.start_key, edge.end_key) for edge in graph_data.edge_list} == {
        (python_name, router_name),
        (agent_name, end_name),
    }
