"""Node names resolved for a graph's session data come only from that graph.

References stored before same-graph validation existed can still point at a
node in another organization's graph. Building session data must render such
a reference as "unknown node #id" and never expose the foreign node's name.
The rows are created through the ORM to stand in for that pre-existing data.
"""

import pytest

from tables.models import Edge, StartNode
from tables.models.graph_models import (
    ConditionGroup,
    DecisionTableNode,
    Graph,
    PythonNode,
)
from tables.models.python_models import PythonCode
from tables.services.converter_service import ConverterService
from tables.services.session_manager_service import SessionManagerService
from tests.rbac_cross_org_fixtures import beta  # noqa: F401
from utils.graph_utils import NodeNameResolver, resolve_node_names

FOREIGN_NAME = "foreign-org-private-name"


def _python_node(graph: Graph, node_name: str, node_number: int) -> PythonNode:
    return PythonNode.objects.create(
        graph=graph,
        node_name=node_name,
        node_number=node_number,
        python_code=PythonCode.objects.create(code="def main(): return 1"),
    )


@pytest.fixture
def foreign_node(beta) -> PythonNode:  # noqa: F811
    return _python_node(Graph.objects.create(name="beta graph", org=beta), FOREIGN_NAME, node_number=9)


@pytest.fixture
def local_node(graph) -> PythonNode:
    return _python_node(graph, "local", node_number=3)


@pytest.mark.django_db
def test_resolve_node_names_hides_nodes_outside_the_graphs(graph, local_node, foreign_node):
    names = resolve_node_names([local_node.id, foreign_node.id], graph_ids=[graph.id])

    assert names == {
        local_node.id: f"local #3 #{local_node.id}",
        foreign_node.id: f"unknown node #{foreign_node.id}",
    }


@pytest.mark.django_db
def test_graph_scoped_resolver_fallback_hides_foreign_node(graph, local_node, foreign_node):
    resolver = NodeNameResolver(graph_id=graph.id)

    assert resolver(local_node.id) == f"local #3 #{local_node.id}"
    assert resolver(foreign_node.id) == f"unknown node #{foreign_node.id}"


@pytest.mark.django_db
def test_session_graph_data_does_not_expose_foreign_node_names(graph, local_node, foreign_node):
    start_node = StartNode.objects.create(graph=graph, variables={})
    Edge.objects.create(graph=graph, start_node_id=start_node.id, end_node_id=local_node.id)
    Edge.objects.create(graph=graph, start_node_id=local_node.id, end_node_id=foreign_node.id)
    decision_table = DecisionTableNode.objects.create(
        graph=graph, node_name="router", default_next_node_id=foreign_node.id
    )
    ConditionGroup.objects.create(
        decision_table_node=decision_table,
        group_name="group",
        group_type="simple",
        order=0,
        next_node_id=foreign_node.id,
    )

    graph_data = SessionManagerService()._build_graph_data(
        graph, None, None, start_node=start_node
    )

    assert FOREIGN_NAME not in graph_data.model_dump_json()
    unknown = f"unknown node #{foreign_node.id}"
    [decision_table_data] = graph_data.decision_table_node_list
    assert decision_table_data.default_next_node == unknown
    assert decision_table_data.conditional_group_list[0].next_node == unknown
    assert unknown in {edge.end_key for edge in graph_data.edge_list}


@pytest.mark.django_db
def test_graph_scoped_resolver_memoizes_a_cache_miss(
    graph, local_node, django_assert_num_queries
):
    resolver = NodeNameResolver(graph_id=graph.id)
    first = resolver(local_node.id)

    with django_assert_num_queries(0):
        assert resolver(local_node.id) == first == f"local #3 #{local_node.id}"


@pytest.mark.parametrize(
    "converter_method",
    [
        "convert_edge_to_pytdantic",
        "convert_decision_table_node_to_pydantic",
        "convert_condition_group_to_pydantic",
        "convert_classification_decision_table_node_to_pydantic",
    ],
)
def test_converter_rendering_a_stored_node_reference_requires_an_explicit_resolver(
    converter_method,
):
    # The default resolver is unscoped: falling back to it for a stored reference
    # would render another organization's node name.
    method = getattr(ConverterService(), converter_method)

    with pytest.raises(TypeError, match="required keyword-only argument: 'resolver'"):
        method(object())
