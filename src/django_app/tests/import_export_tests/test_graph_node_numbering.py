import pytest

from tables.models import AgentNode, Crew, CrewNode
from tables.import_export.registry import entity_registry
from tables.import_export.enums import EntityType, NodeType
from tables.import_export.id_mapper import IDMapper


@pytest.fixture
def legacy_crew(db, default_org):
    """A leftover Crew row: the model survives for backward compatibility even
    though its API/execution surface is gone."""
    return Crew.objects.create(name="legacy crew", org=default_org)


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

    def test_returns_highest_node_number(self, graph):
        AgentNode.objects.create(graph=graph, node_name="a", metadata={"nodeNumber": 3})
        AgentNode.objects.create(graph=graph, node_name="b", metadata={"nodeNumber": 7})
        assert _graph_strategy()._max_node_number(graph) == 7


@pytest.mark.django_db
class TestCrewNodeImportIsSkipped:
    """CrewNode has no import_export strategy anymore (CrewAI execution removed),
    but NodeType.CREW_NODE stays a recognized enum member so old exports still
    parse. `_create_nodes` must skip crew-node entries with a warning instead
    of raising or reviving CrewAI-era nodes."""

    def test_crew_node_payload_is_skipped_not_created(self, graph, legacy_crew):
        _import_one_crew_node(graph, legacy_crew, "Crew #99", {"nodeNumber": 99})
        assert not CrewNode.objects.filter(
            graph=graph, node_name__startswith="Crew"
        ).exists()

    def test_skipped_crew_node_does_not_advance_the_node_number_counter(
        self, graph, legacy_crew
    ):
        AgentNode.objects.create(
            graph=graph, node_name="Existing #50", metadata={"nodeNumber": 50}
        )
        _import_one_crew_node(graph, legacy_crew, "My Node", {})

        assert _graph_strategy()._max_node_number(graph) == 50
