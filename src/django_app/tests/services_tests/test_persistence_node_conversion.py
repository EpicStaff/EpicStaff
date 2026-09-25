import pytest

from tables.models import Edge, PersistenceNode, PersistenceTable, StartNode
from tables.services.converter_service import ConverterService
from tables.services.session_manager_service import SessionManagerService


@pytest.fixture
def node(graph, default_org) -> PersistenceNode:
    table = PersistenceTable.objects.create(org=default_org, name="Customers")
    return PersistenceNode.objects.create(
        graph=graph,
        node_name="persist",
        persistence_table=table,
        mode="write",
        entries=[{"key": "profile_{variables.user.id}", "value": "variables.profile"}],
        input_map={},
    )


@pytest.mark.django_db
def test_converter_maps_every_field(node):
    data = ConverterService().convert_persistence_node_to_pydantic(node)
    assert data.persistence_table_id == node.persistence_table_id
    assert data.mode == "write"
    assert data.entries == node.entries
    assert data.input_map == {}


@pytest.mark.django_db
def test_graph_data_carries_persistence_nodes(graph, node):
    # _build_graph_data requires a resolvable entrypoint before it will return;
    # wire start -> persistence node the same way test_task_node_payload.py does.
    start_node = StartNode.objects.create(graph=graph, variables={})
    Edge.objects.create(graph=graph, start_node_id=start_node.id, end_node_id=node.id)

    # _build_graph_data has no public wrapper; it is the unit that assembles GraphData.
    graph_data = SessionManagerService()._build_graph_data(graph, None, None)
    assert [item.node_name for item in graph_data.persistence_node_list] == [f"persist #{node.id}"]
