from typing import Any, Optional

from tables.models import CrewNode
from tables.import_export.strategies.base import EntityImportExportStrategy
from tables.import_export.serializers.crew_node import CrewNodeImportSerializer
from tables.import_export.enums import EntityType
from tables.import_export.id_mapper import IDMapper


class CrewNodeStrategy(EntityImportExportStrategy):
    entity_type = EntityType.CREW_NODE
    serializer_class = CrewNodeImportSerializer

    def get_instance(self, entity_id: int) -> Optional[CrewNode]:
        return CrewNode.objects.filter(id=entity_id).first()

    def get_preview_data(self, instance: CrewNode) -> dict:
        return {"id": instance.id, "graph": instance.graph_id}

    def extract_dependencies_from_instance(self, instance: CrewNode) -> dict:
        deps = {EntityType.GRAPH: [instance.graph_id]}
        if instance.crew_id:
            deps[EntityType.CREW] = [instance.crew_id]
        return deps

    def export_entity(self, instance: CrewNode) -> dict:
        return self.serializer_class(instance).data

    def create_entity(self, data: dict, id_mapper: IDMapper, **kwargs) -> CrewNode:
        graph_id = id_mapper.get_or_none(EntityType.GRAPH, data.pop("graph", None))
        old_crew_id = data.pop("crew", None)
        data["crew"] = id_mapper.get_or_none(EntityType.CREW, old_crew_id)
        serializer = self.serializer_class(data={**data, "graph": graph_id})
        serializer.is_valid(raise_exception=True)
        return serializer.save()
