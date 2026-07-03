from dataclasses import dataclass, field
from collections import defaultdict

from tables.models.graph_models import Edge
from tables.import_export.registry import EntityRegistry
from tables.import_export.enums import EntityType
from tables.import_export.serializers.graph import EdgeImportSerializer

# Map bulk-save list_key -> EntityType for strategy lookup.
# Start/end nodes are intentionally excluded: they are structural and every
# graph already has them, so they are not part of partial export/import.
LIST_KEY_TO_ENTITY_TYPE: dict[str, EntityType] = {
    "crew_node_list": EntityType.CREW_NODE,
    "python_node_list": EntityType.PYTHON_NODE,
    "audio_transcription_node_list": EntityType.AUDIO_TRANSCRIPTION_NODE,
    "file_extractor_node_list": EntityType.FILE_EXTRACTOR_NODE,
    "telegram_trigger_node_list": EntityType.TELEGRAM_TRIGGER_NODE,
    "webhook_trigger_node_list": EntityType.WEBHOOK_TRIGGER_NODE,
    "decision_table_node_list": EntityType.DECISION_TABLE_NODE,
    "classification_decision_table_node_list": EntityType.CLASSIFICATION_DECISION_TABLE_NODE,
    "subgraph_node_list": EntityType.SUBGRAPH_NODE,
    "graph_note_list": EntityType.NOTE_NODE,
    "code_agent_node_list": EntityType.CODE_AGENT_NODE,
    "schedule_trigger_node_list": EntityType.SCHEDULE_TRIGGER_NODE,
}


@dataclass
class NodeRef:
    entity_type: EntityType
    node_id: int


@dataclass
class PartialExportResult:
    data: dict = field(default_factory=dict)
    errors: list[dict] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return bool(self.errors)


class GraphPartialExportService:
    """
    Export one or several nodes from a graph together with their dependencies.

    When multiple nodes are exported, edges between those nodes
    are included in the result so the selection can be
    re-imported as a coherent unit.

    Errors are collected rather than raised — callers should check
    ``result.has_errors`` before using ``result.data``.
    """

    def __init__(self, registry: EntityRegistry):
        self.registry = registry

    def export(
        self,
        node_refs: list[NodeRef],
        edge_ids: list[int] | None = None,
    ) -> PartialExportResult:
        result = PartialExportResult()

        if not node_refs:
            result.errors.append({"error": "No nodes provided for export."})
            return result

        # Pass 1: resolve node instances
        node_instances: list[tuple[EntityType, object]] = []

        for ref in node_refs:
            strategy = self.registry.get_strategy(ref.entity_type)
            instance = strategy.get_instance(ref.node_id)

            if instance is None:
                result.errors.append(
                    {
                        "node_id": ref.node_id,
                        "entity_type": ref.entity_type,
                        "error": f"Node with id={ref.node_id} not found.",
                    }
                )
                continue

            node_instances.append((ref.entity_type, instance))

        if not node_instances:
            return result

        # Pass 2: export nodes and collect all transitive dependencies,
        # excluding the GRAPH entity itself (nodes are being exported standalone)
        collected: dict[str, dict[int, object]] = defaultdict(dict)

        for entity_type, instance in node_instances:
            self._collect(
                entity_type=entity_type,
                entity_id=instance.id,
                collected=collected,
                exclude_graphs=True,
            )

        # Pass 3: include explicitly requested edges
        if edge_ids:
            edges = list(Edge.objects.filter(id__in=edge_ids))
            missing = set(edge_ids) - {e.id for e in edges}
            for eid in missing:
                result.errors.append(
                    {"edge_id": eid, "error": f"Edge with id={eid} not found."}
                )
            if edges:
                collected["edge_list"] = {e.id: e for e in edges}

        # Pass 4: serialize everything
        result.data = self._serialize(collected)
        return result

    def _collect(
        self,
        entity_type: str,
        entity_id: int,
        collected: dict,
        exclude_graphs: bool = False,
    ) -> None:
        """Recursively collect entity and its dependencies."""
        if entity_id in collected[entity_type]:
            return

        strategy = self.registry.get_strategy(entity_type)
        instance = strategy.get_instance(entity_id)
        if instance is None:
            return

        collected[entity_type][entity_id] = instance

        dependencies = strategy.extract_dependencies_from_instance(instance)

        for dep_type, dep_ids in dependencies.items():
            if exclude_graphs and dep_type == EntityType.GRAPH:
                continue
            for dep_id in dep_ids:
                if dep_id is None:
                    continue
                self._collect(
                    entity_type=dep_type,
                    entity_id=dep_id,
                    collected=collected,
                    exclude_graphs=exclude_graphs,
                )

    def _serialize(self, collected: dict) -> dict:
        """Serialize all collected instances to exportable dicts."""
        result = {}

        for entity_type, instances in collected.items():
            # Edges are serialized separately — they use a dedicated serializer
            if entity_type == "edge_list":
                result["edge_list"] = [
                    EdgeImportSerializer(e).data for e in instances.values()
                ]
                continue

            strategy = self.registry.get_strategy(entity_type)
            result[entity_type] = [
                strategy.export_entity(instance) for instance in instances.values()
            ]

        return result
