from copy import deepcopy

from tables.models import (
    LLMConfig,
    EmbeddingConfig,
    RealtimeConfig,
    RealtimeTranscriptionConfig,
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
    tag_entity: EntityType | None = None

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

    def get_preview_data(self, instance) -> dict:
        return {"id": instance.id, "name": instance.custom_name}

    def extract_dependencies_from_instance(self, instance):
        deps: dict[str, list[int]] = {
            self.model_entity_type: [getattr(instance, self.model_fk_field).id]
        }

        if self.tag_entity:
            tag_ids = list(instance.tags.values_list("id", flat=True))

            if tag_ids:
                deps[self.tag_entity] = tag_ids

        return deps

    def create_entity(self, data, id_mapper: IDMapper, **kwargs):
        if "custom_name" in data:
            existing_names = self.config_model.objects.values_list(
                "custom_name", flat=True
            )
            data["custom_name"] = ensure_unique_identifier(
                base_name=data["custom_name"],
                existing_names=existing_names,
            )

        old_tag_ids = data.pop("tags", [])
        tag_overrides = {}

        if self.tag_entity and old_tag_ids:
            new_tag_ids = [
                id_mapper.get_or_none(self.tag_entity, oid) for oid in old_tag_ids
            ]
            tag_overrides["tags"] = [nid for nid in new_tag_ids if nid is not None]

        resolved_fks = self.remap_foreign_keys(data, id_mapper)
        serializer = self.serializer_class(
            data={**data, **resolved_fks, **tag_overrides}
        )
        serializer.is_valid(raise_exception=True)
        return serializer.save()

    def export_entity(self, instance) -> dict:
        return self.serializer_class(instance).data

    def find_existing(self, data, id_mapper):
        data_copy = deepcopy(data)
        data_copy.pop("id", None)
        data_copy.pop("tags", None)

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
    tag_entity = EntityType.LLM_CONFIG_TAG
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
