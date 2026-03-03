from copy import deepcopy

from tables.models import (
    CrewTag,
    AgentTag,
    GraphTag,
    LLMModelTag,
    EmbeddingModelTag,
    LLMConfigTag,
)

from tables.import_export.strategies.base import EntityImportExportStrategy
from tables.import_export.serializers.tags import (
    CrewTagImportSerializer,
    GraphTagImportSerializer,
    AgentTagImportSerializer,
    LLMConfigTagImportSerializer,
    LLMModelTagImportSerializer,
    EmbeddingModelTagImportSerializer,
)
from tables.import_export.enums import EntityType
from tables.import_export.id_mapper import IDMapper
from tables.import_export.utils import create_filters


class BaseTagStrategy(EntityImportExportStrategy):
    entity_type = None
    serializer_class = None
    model_class = None

    def get_instance(self, entity_id: int):
        return self.model_class.objects.filter(id=entity_id).first()

    def extract_dependencies_from_instance(self, instance):
        return {}

    def create_entity(self, data, id_mapper: IDMapper):
        serializer = self.serializer_class(data=data)
        serializer.is_valid(raise_exception=True)
        return serializer.save()

    def export_entity(self, instance) -> dict:
        return self.serializer_class(instance).data

    def find_existing(self, data, id_mapper):
        data_copy = deepcopy(data)
        data_copy.pop("id", None)

        filters, null_filters = create_filters(data_copy)

        return self.model_class.objects.filter(**filters, **null_filters).first()


class AgentTagStrategy(BaseTagStrategy):
    entity_type = EntityType.AGENT_TAG
    serializer_class = AgentTagImportSerializer
    model_class = AgentTag


class CrewTagStrategy(BaseTagStrategy):
    entity_type = EntityType.CREW_TAG
    serializer_class = CrewTagImportSerializer
    model_class = CrewTag


class GraphTagStrategy(BaseTagStrategy):
    entity_type = EntityType.GRAPH_TAG
    serializer_class = GraphTagImportSerializer
    model_class = GraphTag


class LLMModelTagStrategy(BaseTagStrategy):
    entity_type = EntityType.LLM_MODEL_TAG
    serializer_class = LLMModelTagImportSerializer
    model_class = LLMModelTag


class EmbeddingModelTagStrategy(BaseTagStrategy):
    entity_type = EntityType.EMBEDDING_MODEL_TAG
    serializer_class = EmbeddingModelTagImportSerializer
    model_class = EmbeddingModelTag


class LLMConfigTagStrategy(BaseTagStrategy):
    entity_type = EntityType.LLM_CONFIG_TAG
    serializer_class = LLMConfigTagImportSerializer
    model_class = LLMConfigTag
