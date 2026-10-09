"""Node names resolved for a graph's session data come only from that graph.

References stored before same-graph validation existed can still point at a
node in another organization's graph. Building session data must render such
a reference as "unknown node #id" and never expose the foreign node's name.
The rows are created through the ORM to stand in for that pre-existing data.
"""

import pytest

from tables.models import Edge, StartNode
from tables.models.graph_models import (
    ConditionalEdge,
    ConditionGroup,
    DecisionTableNode,
    Graph,
    PythonNode,
)
from tables.models.python_models import PythonCode
from tables.services.secrets import secret_service
from tables.services.secrets.usage_service import secret_usage_service
from tables.services.session_manager_service import SessionManagerService
from tests.rbac_cross_org_fixtures import beta  # noqa: F401
from rbac.access.effective import EffectivePermissions
from utils.graph_utils import NodeNameResolver, resolve_node_names

FOREIGN_NAME = "foreign-org-private-name"


def _python_node(graph: Graph, node_name: str) -> PythonNode:
    return PythonNode.objects.create(
        graph=graph,
        node_name=node_name,
        python_code=PythonCode.objects.create(code="def main(): return 1"),
    )


@pytest.fixture
def foreign_node(beta) -> PythonNode:  # noqa: F811
    return _python_node(Graph.objects.create(name="beta graph", org=beta), FOREIGN_NAME)


@pytest.fixture
def local_node(graph) -> PythonNode:
    return _python_node(graph, "local")


@pytest.mark.django_db
def test_resolve_node_names_hides_nodes_outside_the_graphs(graph, local_node, foreign_node):
    names = resolve_node_names([local_node.id, foreign_node.id], graph_ids=[graph.id])

    assert names == {
        local_node.id: f"local #{local_node.id}",
        foreign_node.id: f"unknown node #{foreign_node.id}",
    }


@pytest.mark.django_db
def test_graph_scoped_resolver_fallback_hides_foreign_node(graph, local_node, foreign_node):
    resolver = NodeNameResolver(graph_id=graph.id)

    assert resolver(local_node.id) == f"local #{local_node.id}"
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
    ConditionalEdge.objects.create(
        graph=graph,
        source_node_id=foreign_node.id,
        python_code=PythonCode.objects.create(code="def main(): return True"),
    )

    graph_data = SessionManagerService()._build_graph_data(graph, None, None)

    assert FOREIGN_NAME not in graph_data.model_dump_json()
    unknown = f"unknown node #{foreign_node.id}"
    [decision_table_data] = graph_data.decision_table_node_list
    assert decision_table_data.default_next_node == unknown
    assert decision_table_data.conditional_group_list[0].next_node == unknown
    assert unknown in {edge.end_key for edge in graph_data.edge_list}
    assert [edge.source for edge in graph_data.conditional_edge_list] == [unknown]


@pytest.mark.django_db
def test_secret_usage_does_not_expose_foreign_conditional_edge_source(
    default_org, graph, local_node, foreign_node
):
    secret = secret_service.create(text="sk-scope", org=default_org, name="SCOPE_KEY")
    for source in (local_node, foreign_node):
        edge_code = PythonCode.objects.create(
            code='def main(**kwargs):\n    return get_secret("SCOPE_KEY")\n'
        )
        edge_code.secrets.set([secret])
        ConditionalEdge.objects.create(graph=graph, source_node_id=source.id, python_code=edge_code)

    summary = secret_usage_service.summary(
        secret=secret,
        effective=EffectivePermissions(is_superadmin=True, role=None, by_resource={}),
    )

    assert "local" in str(summary)
    assert FOREIGN_NAME not in str(summary)


@pytest.mark.django_db
def test_graph_scoped_resolver_memoizes_a_cache_miss(
    graph, local_node, django_assert_num_queries
):
    resolver = NodeNameResolver(graph_id=graph.id)
    first = resolver(local_node.id)

    with django_assert_num_queries(0):
        assert resolver(local_node.id) == first == f"local #{local_node.id}"
