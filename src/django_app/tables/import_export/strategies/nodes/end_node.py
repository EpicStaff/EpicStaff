from typing import Optional

from tables.models import EndNode
from tables.import_export.strategies.base import EntityImportExportStrategy
from tables.import_export.serializers.end_node import EndNodeImportSerializer
from tables.import_export.enums import EntityType
from tables.import_export.id_mapper import IDMapper


class EndNodeStrategy(EntityImportExportStrategy):
    entity_type = EntityType.END_NODE
    serializer_class = EndNodeImportSerializer

    def get_instance(self, entity_id: int) -> Optional[EndNode]:
        return EndNode.objects.filter(id=entity_id).first()

    def get_preview_data(self, instance: EndNode) -> dict:
        return {"id": instance.id, "graph": instance.graph_id}

    def extract_dependencies_from_instance(self, instance: EndNode) -> dict:
        return {EntityType.GRAPH: [instance.graph_id]}

    def export_entity(self, instance: EndNode) -> dict:
        return self.serializer_class(instance).data

    def create_entity(self, data: dict, id_mapper: IDMapper, **kwargs) -> EndNode:
        graph_id = id_mapper.get_or_none(EntityType.GRAPH, data.pop("graph", None))
        serializer = self.serializer_class(data={**data, "graph": graph_id})
        serializer.is_valid(raise_exception=True)
        return serializer.save()
