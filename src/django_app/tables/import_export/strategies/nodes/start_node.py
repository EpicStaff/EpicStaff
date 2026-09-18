from typing import Any, Optional

from tables.models import StartNode
from tables.import_export.strategies.base import EntityImportExportStrategy
from tables.import_export.serializers.start_node import StartNodeImportSerializer
from tables.import_export.enums import EntityType
from tables.import_export.id_mapper import IDMapper


class StartNodeStrategy(EntityImportExportStrategy):
    entity_type = EntityType.START_NODE
    serializer_class = StartNodeImportSerializer

    def get_instance(self, entity_id: int) -> Optional[StartNode]:
        return StartNode.objects.filter(id=entity_id).first()

    def get_preview_data(self, instance: StartNode) -> dict:
        return {"id": instance.id, "graph": instance.graph_id}

    def extract_dependencies_from_instance(self, instance: StartNode) -> dict:
        return {EntityType.GRAPH: [instance.graph_id]}

    def export_entity(self, instance: StartNode) -> dict:
        return self.serializer_class(instance).data

    def create_entity(self, data: dict, id_mapper: IDMapper, **kwargs) -> StartNode:
        graph_id = id_mapper.get_or_none(EntityType.GRAPH, data.pop("graph", None))
        serializer = self.serializer_class(data={**data, "graph": graph_id})
        serializer.is_valid(raise_exception=True)
        return serializer.save()
