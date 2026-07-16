"""
AgentNode/TaskNode import/export coverage.

Verifies the two node types round-trip through GraphStrategy export/import
(NODE_HANDLERS registration in tables/import_export/strategies/node_handlers.py),
with AgentNode's ordered AgentNodeTask children (and their context_tasks
references) inlined the same way DecisionTableNode/CDT inline condition groups.

`agent_definition`/`surface_list` are intentionally NOT tracked by the
import/export system (same boundary as Agent.knowledge_collection) — the
imported node lands with no agent assigned, which is a supported, documented
state (see AgentNode.agent_definition / TaskNode.agent_definition help_text).
"""

from copy import deepcopy

import pytest

from tables.models import AgentNode, AgentNodeTask, Organization, TaskNode
from tables.constants.organization_constants import DEFAULT_ORGANIZATION_NAME
from tables.import_export.enums import EntityType
from tables.import_export.id_mapper import IDMapper
from tables.import_export.registry import entity_registry


@pytest.fixture
def default_org(db):
    """GraphStrategy.create_entity requires the org named by
    DEFAULT_ORGANIZATION_NAME to exist — matches the local override in
    test_strategies.py, not the differently-named global conftest fixture."""
    return Organization.objects.get_or_create(name=DEFAULT_ORGANIZATION_NAME)[0]


def _get_strategy(entity_type):
    return entity_registry.get_strategy(entity_type)


def _build_identity_mapper(export_data):
    """Build an IDMapper where every old ID maps to itself (for tests against existing DB)."""
    mapper = IDMapper()
    for entity_type, entities in export_data.items():
        if entity_type == "main_entity":
            continue
        if isinstance(entities, list):
            for entity in entities:
                if isinstance(entity, dict) and "id" in entity:
                    mapper.map(
                        entity_type, entity["id"], entity["id"], was_created=False
                    )
    return mapper


@pytest.mark.django_db
class TestAgentNodeTaskNodeRoundTrip:
    def _seed_nodes(self, graph):
        agent_node = AgentNode.objects.create(graph=graph, node_name="agent_node_1")
        task_a = AgentNodeTask.objects.create(
            agent_node=agent_node,
            name="step_a",
            order=0,
            instructions="do step a",
        )
        task_b = AgentNodeTask.objects.create(
            agent_node=agent_node,
            name="step_b",
            order=1,
            instructions="do step b",
            output_schema={"type": "object", "properties": {"ok": {"type": "boolean"}}},
        )
        task_b.context_tasks.set([task_a])

        task_node = TaskNode.objects.create(
            graph=graph,
            node_name="task_node_1",
            instructions="standalone task instructions",
            output_schema={"type": "string"},
        )
        return agent_node, task_node

    def test_node_types_are_exported(self, rich_seeded_db, export_service):
        graph = rich_seeded_db["graph"]
        self._seed_nodes(graph)

        strategy = _get_strategy(EntityType.GRAPH)
        data = strategy.export_entity(graph)

        node_types = {node["node_type"] for node in data["nodes"]}
        assert "AgentNode" in node_types
        assert "TaskNode" in node_types

        agent_node_export = next(
            n for n in data["nodes"] if n["node_type"] == "AgentNode"
        )
        assert len(agent_node_export["tasks"]) == 2
        assert "agent_definition" not in agent_node_export
        assert "surface_list" not in agent_node_export

    def test_round_trip_preserves_tasks_and_context(
        self, rich_seeded_db, export_service, default_org
    ):
        graph = rich_seeded_db["graph"]
        self._seed_nodes(graph)

        export_data = export_service.export_entities(EntityType.GRAPH, [graph.id])
        mapper = _build_identity_mapper(export_data)
        strategy = _get_strategy(EntityType.GRAPH)
        graph_data = deepcopy(export_data[EntityType.GRAPH][0])

        agent_node_count_before = AgentNode.objects.count()
        task_node_count_before = TaskNode.objects.count()
        task_count_before = AgentNodeTask.objects.count()

        new_graph = strategy.create_entity(graph_data, mapper)

        assert AgentNode.objects.count() == agent_node_count_before + 1
        assert TaskNode.objects.count() == task_node_count_before + 1
        assert AgentNodeTask.objects.count() == task_count_before + 2

        new_agent_node = new_graph.agent_node_list.get()
        # Untracked cross-cutting FK — dropped, not silently mis-linked to the
        # wrong (old) AgentDefinition row.
        assert new_agent_node.agent_definition_id is None

        new_tasks = list(new_agent_node.tasks.order_by("order"))
        assert [task.name for task in new_tasks] == ["step_a", "step_b"]
        assert new_tasks[1].output_schema == {
            "type": "object",
            "properties": {"ok": {"type": "boolean"}},
        }

        # context_tasks must point at the NEW sibling task, not the old one.
        resolved_context_tasks = list(new_tasks[1].context_tasks.all())
        assert resolved_context_tasks == [new_tasks[0]]
        assert resolved_context_tasks[0].agent_node_id == new_agent_node.id

        new_task_node = new_graph.task_node_list.get()
        assert new_task_node.instructions == "standalone task instructions"
        assert new_task_node.output_schema == {"type": "string"}
        assert new_task_node.agent_definition_id is None
