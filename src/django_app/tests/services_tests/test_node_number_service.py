import threading
from datetime import datetime, timezone

import pytest
from django.db import connection

from tables.models import AgentNode, DecisionTableNode, Graph
from tables.services.node_number_service import NodeNumberService, source_order


@pytest.mark.django_db
def test_reserve_returns_consecutive_block_above_counter(graph):
    assert list(NodeNumberService().reserve(graph.id, 3)) == [1, 2, 3]
    assert list(NodeNumberService().reserve(graph.id, 2)) == [4, 5]
    graph.refresh_from_db()
    assert graph.node_number_seq == 5


@pytest.mark.django_db
def test_reserve_zero_issues_nothing_and_leaves_counter(graph):
    assert list(NodeNumberService().reserve(graph.id, 0)) == []
    graph.refresh_from_db()
    assert graph.node_number_seq == 0


@pytest.mark.django_db
def test_counters_of_different_graphs_are_independent(graph, default_org):
    other_graph = Graph.objects.create(name="other", org=default_org)
    NodeNumberService().reserve(graph.id, 4)
    assert list(NodeNumberService().reserve(other_graph.id, 2)) == [1, 2]


@pytest.mark.django_db
def test_reserve_reaches_a_soft_deleted_graph(graph):
    Graph.all_objects.filter(pk=graph.pk).update(
        active=False, soft_deleted_at=datetime.now(timezone.utc)
    )
    assert list(NodeNumberService().reserve(graph.id, 1)) == [1]


@pytest.mark.django_db
def test_raise_to_never_lowers(graph):
    NodeNumberService().raise_to(graph.id, 9)
    NodeNumberService().raise_to(graph.id, 4)
    graph.refresh_from_db()
    assert graph.node_number_seq == 9


@pytest.mark.django_db
def test_new_node_gets_next_number_and_keeps_it_on_update(graph):
    first = AgentNode.objects.create(graph=graph, node_name="A")
    second = AgentNode.objects.create(graph=graph, node_name="A")
    second.node_name = "B"
    second.save()
    second.refresh_from_db()
    assert (first.node_number, second.node_number) == (1, 2)


@pytest.mark.django_db
def test_update_never_assigns_a_number_to_an_unnumbered_node(graph):
    node = AgentNode.objects.create(graph=graph, node_name="A")
    AgentNode.objects.filter(pk=node.pk).update(node_number=None)
    node.refresh_from_db()
    node.node_name = "B"
    node.save()
    node.refresh_from_db()
    assert node.node_number is None
    graph.refresh_from_db()
    assert graph.node_number_seq == 1


@pytest.mark.django_db
def test_node_without_a_name_still_gets_a_number(graph):
    node = AgentNode.objects.create(graph=graph)
    node.refresh_from_db()
    assert node.node_number == 1
    assert node.node_name == f"agentnode_{node.pk}"


@pytest.mark.django_db
def test_numbers_are_shared_across_node_types_of_one_graph(graph):
    agent_node = AgentNode.objects.create(graph=graph, node_name="A")
    table_node = DecisionTableNode.objects.create(graph=graph, node_name="T")
    assert (agent_node.node_number, table_node.node_number) == (1, 2)


@pytest.mark.django_db
def test_deleted_number_is_not_reused(graph):
    AgentNode.objects.create(graph=graph, node_name="A")
    doomed = AgentNode.objects.create(graph=graph, node_name="B")
    doomed.delete()
    assert AgentNode.objects.create(graph=graph, node_name="C").node_number == 3


@pytest.mark.django_db
def test_supplied_number_is_kept_and_raises_counter(graph):
    AgentNode.objects.create(graph=graph, node_name="Copied", node_number=7)
    assert AgentNode.objects.create(graph=graph, node_name="New").node_number == 8


@pytest.mark.django_db
def test_supplied_number_below_counter_does_not_lower_it(graph):
    NodeNumberService().reserve(graph.id, 5)
    AgentNode.objects.create(graph=graph, node_name="Copied", node_number=2)
    graph.refresh_from_db()
    assert graph.node_number_seq == 5


@pytest.mark.django_db
def test_restart_refuses_a_graph_that_still_has_a_node(graph):
    AgentNode.objects.create(graph=graph, node_name="A")
    with pytest.raises(ValueError):
        NodeNumberService().restart(graph.id)
    graph.refresh_from_db()
    assert graph.node_number_seq == 1


@pytest.mark.django_db
def test_restart_refuses_a_graph_that_only_has_a_soft_deleted_node(graph):
    node = DecisionTableNode.objects.create(graph=graph, node_name="T")
    DecisionTableNode.all_objects.filter(pk=node.pk).update(
        active=False, soft_deleted_at=datetime.now(timezone.utc)
    )
    with pytest.raises(ValueError):
        NodeNumberService().restart(graph.id)


@pytest.mark.django_db
def test_restart_resets_an_empty_graph(graph):
    AgentNode.objects.create(graph=graph, node_name="A").delete()
    NodeNumberService().restart(graph.id)
    graph.refresh_from_db()
    assert graph.node_number_seq == 0
    assert AgentNode.objects.create(graph=graph, node_name="B").node_number == 1


@pytest.mark.django_db(transaction=True)
def test_concurrent_reserves_never_overlap(graph):
    results: list[range] = []

    def worker():
        try:
            results.append(NodeNumberService().reserve(graph.id, 5))
        finally:
            connection.close()

    threads = [threading.Thread(target=worker) for _ in range(8)]
    [thread.start() for thread in threads]
    [thread.join() for thread in threads]
    issued = [number for block in results for number in block]
    assert sorted(issued) == list(range(1, 41))


@pytest.mark.parametrize(
    ("numbers_by_key", "expected"),
    [
        ({10: 4, 11: 1, 12: None, 13: 5}, {11: 1, 10: 2, 13: 3, 12: 4}),
        ({}, {}),
        ({"a": 1, "b": 4, "c": 5}, {"a": 1, "b": 2, "c": 3}),
        ({3: 2, 1: 2, 2: 2}, {1: 1, 2: 2, 3: 3}),
        ({9: None, 4: None}, {4: 1, 9: 2}),
    ],
)
def test_source_order_renumbers_from_one_keeping_source_order(numbers_by_key, expected):
    assert source_order(numbers_by_key) == expected
