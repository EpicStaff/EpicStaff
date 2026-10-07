from tables.import_export.enums import EntityType
from tables.import_export.id_mapper import IDMapper
from tables.import_export.serializers.session import (
    GraphSessionMessageExportSerializer,
    SessionExportSerializer,
)
from tables.import_export.strategies.base import EntityImportExportStrategy
from tables.models.session_models import Session

_NODE_LIST_SUFFIXES = ("_node_list", "_node_data_list")


def _node_types_by_name(graph_schema: dict) -> dict[str, str]:
    """Map node_name to node type: `task_node_list` -> `task`, `end_node` -> `end`."""
    node_types = {}
    end_node = graph_schema.get("end_node")
    if end_node:
        node_types[end_node.get("node_name")] = "end"
    for key, nodes in graph_schema.items():
        for suffix in _NODE_LIST_SUFFIXES:
            if key.endswith(suffix):
                for node in nodes or []:
                    node_types[node.get("node_name")] = key.removesuffix(suffix)
    return node_types


class SessionStrategy(EntityImportExportStrategy):
    entity_type = EntityType.SESSION

    def get_instance(self, entity_id: int) -> Session:
        return (
            Session.objects.filter(id=entity_id)
            .select_related("trigger", "principal", "graph")
            .first()
        )

    def get_preview_data(self, instance: Session) -> dict:
        return {"id": instance.id, "status": instance.status}

    def extract_dependencies_from_instance(self, instance: Session) -> dict:
        sub_ids = list(instance.subgraph_sessions.values_list("id", flat=True))
        return {EntityType.SESSION: sub_ids}

    def export_entity(self, instance: Session) -> dict:
        return {
            "session": {
                **SessionExportSerializer(instance).data,
                "node_types": _node_types_by_name(instance.graph_schema),
            },
            "messages": list(
                GraphSessionMessageExportSerializer(
                    instance.graphsessionmessage_set.all().order_by("created_at", "id"),
                    many=True,
                ).data
            ),
        }

    def create_entity(self, data: dict, id_mapper: IDMapper, **kwargs):
        raise NotImplementedError("Session export is read-only")
