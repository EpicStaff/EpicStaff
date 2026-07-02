from django.db import transaction
from rest_framework.exceptions import ValidationError

from tables.models import Graph
from tables.import_export.id_mapper import IDMapper
from tables.import_export.registry import EntityRegistry
from tables.import_export.constants import DEPENDENCY_ORDER
from tables.import_export.enums import EntityType
from tables.import_export.strategies.graph import GraphStrategy


# Node entity types that belong to a graph — handled via recreate_graph_children.
# Start/end nodes are intentionally excluded: they are structural and every
# graph already has them, so they are not part of partial export/import.
_NODE_ENTITY_TYPES = {
    EntityType.CREW_NODE,
    EntityType.PYTHON_NODE,
    EntityType.AUDIO_TRANSCRIPTION_NODE,
    EntityType.FILE_EXTRACTOR_NODE,
    EntityType.TELEGRAM_TRIGGER_NODE,
    EntityType.WEBHOOK_TRIGGER_NODE,
    EntityType.DECISION_TABLE_NODE,
    EntityType.CLASSIFICATION_DECISION_TABLE_NODE,
    EntityType.SUBGRAPH_NODE,
    EntityType.NOTE_NODE,
    EntityType.CODE_AGENT_NODE,
    EntityType.SCHEDULE_TRIGGER_NODE,
}


class PartialImportService:
    """
    Import the output of GraphPartialExportService (partial-export) into an
    existing graph identified by graph_id.

    The export file contains standalone nodes (with their transitive
    dependencies) and optionally edges.  The graph itself is NOT re-created;
    nodes are appended to the existing graph and all IDs are remapped via
    IDMapper.
    """

    def __init__(self, registry: EntityRegistry):
        self.registry = registry

    def import_data(self, export_data: dict, graph: Graph) -> IDMapper:
        nodes_data = self._collect_nodes(export_data)
        if not nodes_data:
            raise ValidationError({"detail": "No nodes found in the import file."})

        id_mapper = IDMapper()

        with transaction.atomic():
            # Step 1: import non-node dependencies (LLM configs, crews, etc.)
            self._import_dependencies(export_data, id_mapper)

            # Step 2: build a graph-children payload from the export data
            # and create nodes + edges inside the existing graph
            graph_strategy: GraphStrategy = self.registry.get_strategy(EntityType.GRAPH)

            edges_data = export_data.get("edge_list", [])

            graph_strategy.recreate_graph_children(
                graph,
                {
                    "nodes": nodes_data,
                    "edge_list": edges_data,
                },
                id_mapper,
                is_partial=True,
            )

        return id_mapper

    def _import_dependencies(self, export_data: dict, id_mapper: IDMapper) -> None:
        """Import all non-node, non-graph entity types in dependency order."""
        dep_types = [
            et
            for et in DEPENDENCY_ORDER
            if et not in _NODE_ENTITY_TYPES
            and et != EntityType.GRAPH
            and et in export_data
        ]

        for entity_type in dep_types:
            strategy = self.registry.get_strategy(entity_type)
            for entity_data in export_data.get(entity_type, []):
                old_id = entity_data["id"]
                existing = strategy.find_existing(entity_data, id_mapper)
                was_created = existing is None
                instance = strategy.import_entity(entity_data, id_mapper, is_main=False)
                if instance is not None:
                    id_mapper.map(entity_type, old_id, instance.id, was_created)

    def _collect_nodes(self, export_data: dict) -> list:
        """
        Gather node dicts from all node entity types and tag each with
        node_type so GraphStrategy._create_nodes can dispatch correctly.
        """
        nodes = []
        for entity_type in _NODE_ENTITY_TYPES:
            for node_data in export_data.get(entity_type, []):
                node_copy = dict(node_data)
                node_copy["node_type"] = entity_type
                nodes.append(node_copy)
        return nodes
