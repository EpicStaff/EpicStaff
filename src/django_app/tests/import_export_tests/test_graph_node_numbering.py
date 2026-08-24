import pytest

from tables.models import CrewNode
from tables.import_export.registry import entity_registry
from tables.import_export.enums import EntityType, NodeType
from tables.import_export.id_mapper import IDMapper


def _graph_strategy():
    return entity_registry.get_strategy(EntityType.GRAPH)


def _import_one_crew_node(graph, crew, node_name, metadata):
    """Run _create_nodes with a single crew-node payload into `graph`."""
    strategy = _graph_strategy()
    id_mapper = IDMapper()
    id_mapper.map(EntityType.CREW, crew.id, crew.id, was_created=False)
    node_mapper = IDMapper()
    nodes_data = [
        {
            "id": 9999,
            "node_type": NodeType.CREW_NODE,
            "crew": crew.id,
            "node_name": node_name,
            "metadata": dict(metadata),
        }
    ]
    strategy._create_nodes(nodes_data, graph, node_mapper, id_mapper)


@pytest.mark.django_db
class TestMaxNodeNumber:
    def test_returns_zero_when_no_node_numbers(self, graph):
        assert _graph_strategy()._max_node_number(graph) == 0

    def test_returns_highest_node_number(self, graph, crew):
        CrewNode.objects.create(
            graph=graph, crew=crew, node_name="a", metadata={"nodeNumber": 3}
        )
        CrewNode.objects.create(
            graph=graph, crew=crew, node_name="b", metadata={"nodeNumber": 7}
        )
        assert _graph_strategy()._max_node_number(graph) == 7


@pytest.mark.django_db
class TestNodeRenamingOnImport:
    def test_auto_name_is_renumbered(self, graph, crew):
        _import_one_crew_node(graph, crew, "Crew #99", {"nodeNumber": 99})
        node = CrewNode.objects.get(node_name="Crew #1")
        assert node.metadata["nodeNumber"] == 1

    def test_custom_name_gets_number_appended(self, graph, crew):
        _import_one_crew_node(graph, crew, "My Node", {})
        node = CrewNode.objects.get(node_name="My Node #1")
        assert node.metadata["nodeNumber"] == 1

    def test_counter_continues_above_existing_max(self, graph, crew):
        CrewNode.objects.create(
            graph=graph,
            crew=crew,
            node_name="Existing #50",
            metadata={"nodeNumber": 50},
        )
        _import_one_crew_node(graph, crew, "My Node", {})
        node = CrewNode.objects.get(node_name="My Node #51")
        assert node.metadata["nodeNumber"] == 51
