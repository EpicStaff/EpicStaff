from typing import Optional

from tables.models import AudioTranscriptionNode
from tables.import_export.strategies.base import EntityImportExportStrategy
from tables.import_export.serializers.audio_transcription_node import (
    AudioTranscriptionNodeImportSerializer,
)
from tables.import_export.enums import EntityType
from tables.import_export.id_mapper import IDMapper


class AudioTranscriptionNodeStrategy(EntityImportExportStrategy):
    entity_type = EntityType.AUDIO_TRANSCRIPTION_NODE
    serializer_class = AudioTranscriptionNodeImportSerializer

    def get_instance(self, entity_id: int) -> Optional[AudioTranscriptionNode]:
        return AudioTranscriptionNode.objects.filter(id=entity_id).first()

    def get_preview_data(self, instance: AudioTranscriptionNode) -> dict:
        return {"id": instance.id, "graph": instance.graph_id}

    def extract_dependencies_from_instance(
        self, instance: AudioTranscriptionNode
    ) -> dict:
        return {EntityType.GRAPH: [instance.graph_id]}

    def export_entity(self, instance: AudioTranscriptionNode) -> dict:
        return self.serializer_class(instance).data

    def create_entity(
        self, data: dict, id_mapper: IDMapper, **kwargs
    ) -> AudioTranscriptionNode:
        graph_id = id_mapper.get_or_none(EntityType.GRAPH, data.pop("graph", None))
        serializer = self.serializer_class(data={**data, "graph": graph_id})
        serializer.is_valid(raise_exception=True)
        return serializer.save()
