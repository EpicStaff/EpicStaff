from copy import deepcopy

from django.db.models import Q
from rbac.authorship import resolve_author
from rest_framework import serializers

from tables.import_export.enums import EntityType
from tables.import_export.id_mapper import IDMapper
from tables.import_export.serializers.configs import (
    ElevenLabsRealtimeConfigImportSerializer,
    EmbeddingConfigImportSerializer,
    GeminiRealtimeConfigImportSerializer,
    LLMConfigImportSerializer,
    OpenAIRealtimeConfigImportSerializer,
    RealtimeConfigImportSerializer,
    RealtimeTranscriptionConfigImportSerializer,
)
from tables.import_export.strategies.base import EntityImportExportStrategy
from tables.import_export.utils import create_filters, ensure_unique_identifier
from tables.models import (
    EmbeddingConfig,
    LLMConfig,
    RealtimeConfig,
    RealtimeTranscriptionConfig,
)
from tables.models.realtime_models import (
    ElevenLabsRealtimeConfig,
    GeminiRealtimeConfig,
    OpenAIRealtimeConfig,
)
from tables.services.secrets.exceptions import SecretUseDeniedError
from tables.services.secrets.policies import LLM_CONFIG_SECRET_POLICY, RowWrite
from tables.services.secrets.reference_guard import SecretActor, secret_reference_guard
from tables.services.secrets.secret_resolver import extract_secret_marker_names

_IMPORT_DENIED = (
    'Importing secret references requires the "Use" permission on Secrets. '
    "Nothing was imported. Ask an organization admin to grant it."
)


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

    def get_org_scope_q(self, org_id: int) -> Q:
        if org_id is None:
            return Q()
        return Q(org_id=org_id)

    def secret_binding_approval(self, data: dict, **kwargs) -> dict:
        """Gate the imported row's secrets and return who approves its binding; none by default."""
        return {}

    def create_entity(self, data, id_mapper: IDMapper, **kwargs):
        org_id = kwargs.get("org_id")
        approval = self.secret_binding_approval(data, **kwargs)
        if "custom_name" in data:
            existing_names = self.config_model.objects.filter(org_id=org_id).values_list(
                "custom_name", flat=True
            )
            data["custom_name"] = ensure_unique_identifier(
                base_name=data["custom_name"],
                existing_names=existing_names,
            )

        old_tag_ids = data.pop("tags", [])
        tag_overrides = {}

        if self.tag_entity and old_tag_ids:
            new_tag_ids = [id_mapper.get_or_none(self.tag_entity, oid) for oid in old_tag_ids]
            tag_overrides["tags"] = [nid for nid in new_tag_ids if nid is not None]

        resolved_fks = self.remap_foreign_keys(data, id_mapper)
        serializer = self.serializer_class(
            data={**data, **resolved_fks, **tag_overrides, "org": org_id}
        )
        serializer.is_valid(raise_exception=True)
        self._assert_markers_permitted(serializer, user=kwargs.get("user"), org_id=org_id)
        return serializer.save(created_by=resolve_author(kwargs.get("user")), **approval)

    def _assert_markers_permitted(self, serializer, *, user, org_id) -> None:
        """Require secrets:USE to create a config whose headers carry secret markers.

        Import always creates the config, so every marker in it is new to the org's
        rows; a reused existing config (find_existing) never reaches here.
        """
        for field_name in self.serializer_class.secret_marker_fields:
            if extract_secret_marker_names(serializer.validated_data.get(field_name)):
                secret_reference_guard.assert_may_use(
                    user=user, org_id=org_id, field_name=field_name
                )

    def export_entity(self, instance) -> dict:
        return self.serializer_class(instance).data

    def find_existing(self, data, id_mapper, org_id: int | None = None):
        data_copy = deepcopy(data)
        data_copy.pop("id", None)
        data_copy.pop("tags", None)

        fk_filters = self.resolve_fk_filters(data_copy, id_mapper)
        filters, null_filters = create_filters(self._known_fields_only(data_copy))

        return (
            self.config_model.objects.filter(
                **filters,
                **null_filters,
                **fk_filters,
                **self._defaults_for_missing_fields(data_copy),
            )
            .filter(self.get_org_scope_q(org_id))
            .first()
        )

    def _known_fields_only(self, data: dict) -> dict:
        # A file from a newer version can carry fields this version does not have;
        # filtering on them would raise FieldError.
        concrete_field_names = {
            name
            for field in self.config_model._meta.concrete_fields
            for name in (field.name, field.attname)
        }
        return {name: value for name, value in data.items() if name in concrete_field_names}

    def _defaults_for_missing_fields(self, data: dict) -> dict:
        """Filter missing imported fields on the value create_entity would store for them.

        A file from an older version lacks fields added since. Its config is created
        with each such field's model default, so only a config holding those defaults
        is equivalent. Without this an older file would reuse a config whose newer
        settings (e.g. a reasoning effort) differ from what the file describes.
        Fields the import serializer does not write (created_at, secrets) are not
        part of the comparison.
        """
        writable_field_names = {
            name for name, field in self.serializer_class().fields.items() if not field.read_only
        }
        filters = {}
        for field in self.config_model._meta.concrete_fields:
            if (
                field.primary_key
                or field.is_relation
                or field.name in data
                or field.name not in writable_field_names
            ):
                continue
            default = field.get_default()
            if default is None:
                filters[f"{field.name}__isnull"] = True
            else:
                filters[field.name] = default
        return filters

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

    def secret_binding_approval(self, data: dict, **kwargs) -> dict:
        # Secret FKs never travel in a file, but header markers do, and they resolve
        # by name against the importing org's secrets -- so a file written elsewhere
        # must not attach this org's secrets for a caller without USE. A reused config
        # (find_existing) changes nothing and never reaches this.
        user = kwargs.get("user")
        actor = SecretActor(user=user, org_id=kwargs.get("org_id")) if user is not None else None
        try:
            return secret_reference_guard.authorize_write(
                policy=LLM_CONFIG_SECRET_POLICY,
                write=RowWrite.for_new_row(data),
                resolve_actor=lambda: actor,
            )
        except SecretUseDeniedError as denial:
            raise serializers.ValidationError({denial.field_name: _IMPORT_DENIED}) from denial


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


class BaseProviderRealtimeConfigStrategy(EntityImportExportStrategy):
    config_model = None
    serializer_class = None

    def get_instance(self, entity_id: int):
        return self.config_model.objects.filter(id=entity_id).first()

    def get_preview_data(self, instance) -> dict:
        return {"id": instance.id, "name": instance.custom_name}

    def extract_dependencies_from_instance(self, instance) -> dict:
        return {}

    def export_entity(self, instance) -> dict:
        return self.serializer_class(instance).data

    def get_org_scope_q(self, org_id: int) -> Q:
        if org_id is None:
            return Q()
        return Q(org_id=org_id)

    def create_entity(self, data: dict, id_mapper: IDMapper, **kwargs):
        org_id = kwargs.get("org_id")
        existing_names = self.config_model.objects.filter(org_id=org_id).values_list(
            "custom_name", flat=True
        )
        data["custom_name"] = ensure_unique_identifier(
            base_name=data["custom_name"],
            existing_names=existing_names,
        )
        serializer = self.serializer_class(data={**data, "org": org_id})
        serializer.is_valid(raise_exception=True)
        return serializer.save(created_by=resolve_author(kwargs.get("user")))

    def find_existing(self, data: dict, id_mapper: IDMapper, org_id: int | None = None):
        custom_name = data.get("custom_name")
        model_name = data.get("model_name")
        if custom_name and model_name:
            return (
                self.config_model.objects.filter(custom_name=custom_name, model_name=model_name)
                .filter(self.get_org_scope_q(org_id))
                .first()
            )
        return None


class OpenAIRealtimeConfigStrategy(BaseProviderRealtimeConfigStrategy):
    entity_type = EntityType.OPENAI_REALTIME_CONFIG
    config_model = OpenAIRealtimeConfig
    serializer_class = OpenAIRealtimeConfigImportSerializer


class ElevenLabsRealtimeConfigStrategy(BaseProviderRealtimeConfigStrategy):
    entity_type = EntityType.ELEVENLABS_REALTIME_CONFIG
    config_model = ElevenLabsRealtimeConfig
    serializer_class = ElevenLabsRealtimeConfigImportSerializer


class GeminiRealtimeConfigStrategy(BaseProviderRealtimeConfigStrategy):
    entity_type = EntityType.GEMINI_REALTIME_CONFIG
    config_model = GeminiRealtimeConfig
    serializer_class = GeminiRealtimeConfigImportSerializer
