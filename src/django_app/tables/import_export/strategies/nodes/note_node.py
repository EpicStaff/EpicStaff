from typing import Optional

from tables.models.graph_models import GraphNote
from tables.import_export.strategies.base import EntityImportExportStrategy
from tables.import_export.serializers.note_node import GraphNoteImportSerializer
from tables.import_export.enums import EntityType
from tables.import_export.id_mapper import IDMapper


class NoteNodeStrategy(EntityImportExportStrategy):
    entity_type = EntityType.NOTE_NODE
    serializer_class = GraphNoteImportSerializer

    def get_instance(self, entity_id: int) -> Optional[GraphNote]:
        return GraphNote.objects.filter(id=entity_id).first()

    def get_preview_data(self, instance: GraphNote) -> dict:
        return {"id": instance.id, "graph": instance.graph_id}

    def extract_dependencies_from_instance(self, instance: GraphNote) -> dict:
        return {EntityType.GRAPH: [instance.graph_id]}

    def export_entity(self, instance: GraphNote) -> dict:
        return self.serializer_class(instance).data

    def create_entity(self, data: dict, id_mapper: IDMapper, **kwargs) -> GraphNote:
        graph_id = id_mapper.get_or_none(EntityType.GRAPH, data.pop("graph", None))
        serializer = self.serializer_class(data={**data, "graph": graph_id})
        serializer.is_valid(raise_exception=True)
        return serializer.save()
