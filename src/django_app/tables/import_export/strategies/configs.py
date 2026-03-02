from copy import deepcopy

from tables.models import (
    LLMConfig,
    EmbeddingConfig,
    RealtimeConfig,
    RealtimeTranscriptionConfig,
    LLMModel,
    EmbeddingModel,
    RealtimeModel,
    RealtimeTranscriptionModel,
)
from tables.import_export.strategies.base import EntityImportExportStrategy
from tables.import_export.serializers.configs import (
    LLMConfigImportSerializer,
    EmbeddingConfigImportSerializer,
    RealtimeConfigImportSerializer,
    RealtimeTranscriptionConfigImportSerializer,
)
from tables.import_export.enums import EntityType
from tables.import_export.id_mapper import IDMapper
from tables.import_export.utils import ensure_unique_identifier, create_filters


class BaseConfigStrategy(EntityImportExportStrategy):
    entity_type: EntityType
    model_entity_type: EntityType

    config_model = None
    serializer_class = None

    @property
    def model_class(self):
        return self.serializer_class.model_class

    @property
    def provider_field(self):
        return self.serializer_class.provider_field

    @property
    def model_fk_field(self):
        return self.serializer_class.model_fk_field

    @property
    def model_fk_id_field(self):
        return f"{self.model_fk_field}_id"

    def get_instance(self, entity_id: int):
        return self.config_model.objects.filter(id=entity_id).first()

    def extract_dependencies_from_instance(self, instance):
        return {self.model_entity_type: [getattr(instance, self.model_fk_field).id]}

    def create_entity(self, data, id_mapper: IDMapper):
        if "custom_name" in data:
            existing_names = self.config_model.objects.values_list(
                "custom_name", flat=True
            )
            data["custom_name"] = ensure_unique_identifier(
                base_name=data["custom_name"],
                existing_names=existing_names,
            )

        resolved_fks = self.remap_foreign_keys(data, id_mapper)
        serializer = self.serializer_class(data={**data, **resolved_fks})
        serializer.is_valid(raise_exception=True)
        return serializer.save()

    def export_entity(self, instance) -> dict:
        return self.serializer_class(instance).data

    def find_existing(self, data, id_mapper):
        data_copy = deepcopy(data)
        data_copy.pop("id", None)

        fk_filters = self.resolve_fk_filters(data_copy, id_mapper)
        filters, null_filters = create_filters(data_copy)

        return self.config_model.objects.filter(
            **filters,
            **null_filters,
            **fk_filters,
        ).first()

    def remap_foreign_keys(self, data: dict, id_mapper: IDMapper) -> dict:
        old_model_id = data.pop(self.model_fk_field, None)
        return {"model_id": id_mapper.get_or_none(self.model_entity_type, old_model_id)}

    def resolve_fk_filters(self, data: dict, id_mapper: IDMapper) -> dict:
        old_model_id = data.pop(self.model_fk_field, None)
        new_model_id = id_mapper.get_or_none(self.model_entity_type, old_model_id)
        model = self.model_class.objects.get(id=new_model_id)
        return {
            f"{self.model_fk_field}__{self.provider_field}__name": getattr(
                model, self.provider_field
            ).name,
            f"{self.model_fk_field}__name": model.name,
        }


class LLMConfigStrategy(BaseConfigStrategy):
    entity_type = EntityType.LLM_CONFIG
    model_entity_type = EntityType.LLM_MODEL
    config_model = LLMConfig
    serializer_class = LLMConfigImportSerializer


class EmbeddingConfigStrategy(BaseConfigStrategy):
    entity_type = EntityType.EMBEDDING_CONFIG
    model_entity_type = EntityType.EMBEDDING_MODEL
    config_model = EmbeddingConfig
    serializer_class = EmbeddingConfigImportSerializer


class RealtimeConfigStrategy(BaseConfigStrategy):
    entity_type = EntityType.REALTIME_CONFIG
    model_entity_type = EntityType.REALTIME_MODEL
    config_model = RealtimeConfig
    serializer_class = RealtimeConfigImportSerializer


class RealtimeTranscriptionConfigStrategy(BaseConfigStrategy):
    entity_type = EntityType.REALTIME_TRANSCRIPTION_CONFIG
    model_entity_type = EntityType.REALTIME_TRANSCRIPTION_MODEL
    config_model = RealtimeTranscriptionConfig
    serializer_class = RealtimeTranscriptionConfigImportSerializer
