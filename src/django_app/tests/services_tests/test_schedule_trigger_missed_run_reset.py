"""A recorded missed run belongs to the node it happened on, never to a copy of the flow.

Copying a flow, importing an exported one, and restoring a saved version all
produce a node that has never been scheduled here, so none of them carries the
source node's missed run over; the schedule configuration itself is kept.
"""

from datetime import UTC, datetime

import pytest

from tables.graph_versioning.manager import GraphVersioningManager
from tables.import_export.enums import EntityType
from tables.import_export.id_mapper import IDMapper
from tables.import_export.registry import entity_registry
from tables.models import Graph
from tables.models.graph_models import ScheduleTriggerNode
from tables.services.copy_services.graph_copy_service import GraphCopyService

MISSED_START = datetime(2026, 11, 10, 9, 0, tzinfo=UTC)


@pytest.fixture
def missed_node(graph):
    return ScheduleTriggerNode.objects.create(
        graph=graph,
        node_name="once",
        is_active=False,
        run_mode=ScheduleTriggerNode.RunMode.ONCE,
        timezone="Europe/Kyiv",
        start_date_time=MISSED_START,
        end_type=ScheduleTriggerNode.EndType.NEVER,
        missed_run_at=MISSED_START,
    )


def _assert_same_schedule_without_missed_run(node: ScheduleTriggerNode):
    assert node.run_mode == ScheduleTriggerNode.RunMode.ONCE
    assert node.timezone == "Europe/Kyiv"
    assert node.start_date_time == MISSED_START
    assert node.missed_run_at is None


@pytest.mark.django_db
def test_copied_flow_does_not_carry_the_missed_run(missed_node):
    new_graph = GraphCopyService().copy(missed_node.graph, name="Flow copy")

    _assert_same_schedule_without_missed_run(new_graph.schedule_trigger_node_list.get())


@pytest.mark.django_db
def test_imported_node_does_not_carry_the_missed_run(missed_node, default_org):
    strategy = entity_registry.get_strategy(EntityType.SCHEDULE_TRIGGER_NODE)
    exported = strategy.export_entity(missed_node)
    target_graph = Graph.objects.create(name="Imported", org=default_org)
    id_mapper = IDMapper()
    id_mapper.map(EntityType.GRAPH, missed_node.graph_id, target_graph.id)

    imported = strategy.create_entity({**exported, "graph": missed_node.graph_id}, id_mapper)

    imported.refresh_from_db()
    _assert_same_schedule_without_missed_run(imported)


@pytest.mark.django_db
def test_restored_version_does_not_carry_the_missed_run(missed_node):
    manager = GraphVersioningManager()
    graph = missed_node.graph
    snapshot = manager.create_snapshot(graph)

    manager.apply_snapshot_to_graph(graph, snapshot, available_deps={})

    _assert_same_schedule_without_missed_run(graph.schedule_trigger_node_list.get())
