"""Version restore and create-from-version renumber nodes 1..K in source order."""

import pytest

from tables.graph_versioning.services import GraphVersioningService
from tables.models import AgentNode, Crew, CrewNode, Graph, PythonCode, PythonNode, StartNode
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403


def _python_node(graph, node_name, node_number):
    code = PythonCode.objects.create(code="def main(): ...", entrypoint="main", libraries="")
    return PythonNode.objects.create(
        graph=graph, node_name=node_name, python_code=code, node_number=node_number
    )


def _numbers_by_name(graph):
    return {
        **dict(graph.agent_node_list.values_list("node_name", "node_number")),
        **dict(graph.python_node_list.values_list("node_name", "node_number")),
    }


@pytest.fixture
def numbered_flow(acme):
    """A flow whose nodes hold #1, #4 and #5, spread over two node tables."""
    graph = Graph.objects.create(name="Numbered Flow", org=acme)
    StartNode.objects.create(graph=graph, variables={})
    _python_node(graph, "first", 1)
    AgentNode.objects.create(graph=graph, node_name="fourth", node_number=4)
    _python_node(graph, "fifth", 5)
    graph.refresh_from_db()
    return graph


@pytest.fixture
def version(numbered_flow):
    return GraphVersioningService().save_version(numbered_flow, name="three nodes")


def _restore(graph, version):
    graph.refresh_from_db()
    GraphVersioningService().restore_version(
        version, expected_save_version=graph.save_version
    )
    graph.refresh_from_db()


@pytest.mark.django_db
def test_restore_renumbers_one_to_k_in_source_order(numbered_flow, version):
    AgentNode.objects.create(graph=numbered_flow, node_name="added later")

    _restore(numbered_flow, version)

    assert _numbers_by_name(numbered_flow) == {"first": 1, "fourth": 2, "fifth": 3}
    assert numbered_flow.node_number_seq == 3


@pytest.mark.django_db
def test_node_added_after_restore_continues_from_k(numbered_flow, version):
    AgentNode.objects.create(graph=numbered_flow, node_name="added later")
    _restore(numbered_flow, version)

    added = AgentNode.objects.create(graph=numbered_flow, node_name="after restore")

    assert added.node_number == 4


@pytest.mark.django_db
def test_restore_ignores_the_counter_stored_in_the_snapshot(numbered_flow, version):
    version.snapshot["node_number_seq"] = 99
    version.save(update_fields=["snapshot"])

    _restore(numbered_flow, version)

    assert numbered_flow.node_number_seq == 3


@pytest.mark.django_db
def test_create_from_version_numbers_the_new_flow_one_to_k(numbered_flow, version):
    result = GraphVersioningService().create_graph_from_version(version)

    new_graph = Graph.objects.get(pk=result["graph_id"])
    assert _numbers_by_name(new_graph) == {"first": 1, "fourth": 2, "fifth": 3}
    assert new_graph.node_number_seq == 3
    numbered_flow.refresh_from_db()
    assert _numbers_by_name(numbered_flow) == {"first": 1, "fourth": 4, "fifth": 5}
    assert numbered_flow.node_number_seq == 5


@pytest.mark.django_db
def test_create_from_version_ignores_the_counter_stored_in_the_snapshot(version):
    version.snapshot["node_number_seq"] = 99
    version.save(update_fields=["snapshot"])

    result = GraphVersioningService().create_graph_from_version(version)

    assert Graph.objects.get(pk=result["graph_id"]).node_number_seq == 3


@pytest.mark.django_db
def test_restore_numbers_above_a_legacy_crew_node_the_wipe_keeps(acme):
    graph = Graph.objects.create(name="Crew Flow", org=acme)
    _python_node(graph, "python", 1)
    crew_node = CrewNode.objects.create(
        graph=graph,
        node_name="legacy crew",
        crew=Crew.objects.create(org=acme, name="legacy"),
        node_number=4,
    )
    version = GraphVersioningService().save_version(graph, name="with crew node")

    _restore(graph, version)

    assert dict(graph.python_node_list.values_list("node_name", "node_number")) == {"python": 5}
    assert graph.node_number_seq == 5
    assert CrewNode.objects.get(pk=crew_node.pk).node_number == 4
