from copy import deepcopy

from ai_models.domain.specs import ModelKind
from ai_models.models import EmbeddingConfig, LLMConfig
from ai_models.services.config_validation import ConfigValidationService
from django.db.models import Q
from rbac.authorship import resolve_author
from rest_framework.exceptions import ValidationError

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
    SystemOneConfigImportSerializer,
)
from tables.import_export.strategies.base import EntityImportExportStrategy
from tables.import_export.utils import create_filters, ensure_unique_identifier
from tables.models import RealtimeConfig, RealtimeTranscriptionConfig, SystemOneConfig
from tables.models.realtime_models import (
    ElevenLabsRealtimeConfig,
    GeminiRealtimeConfig,
    OpenAIRealtimeConfig,
)
from tables.services.secrets import SecretUseDeniedError
from tables.services.secrets.exceptions import ModelEndpointNotSettableError
from tables.services.secrets.secret_use_checks import (
    SecretUseCheck,
    check_embedding_config_write,
    check_llm_config_write,
)
from tables.services.secrets.secret_use_service import SecretActor


class BaseConfigStrategy(EntityImportExportStrategy):
    entity_type: EntityType
    model_entity_type: EntityType
    tag_entity: EntityType | None = None

    config_model = None
    serializer_class = None
    # The API write path's Secret Use check of this config type, run on every config the
    # import creates; None for a type whose import carries no secret.
    secret_use_check: SecretUseCheck | None = None

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

    def create_entity(self, data, id_mapper: IDMapper, **kwargs):
        org_id = kwargs.get("org_id")
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
        self._check_secret_use(serializer.validated_data, user=kwargs.get("user"), org_id=org_id)
        return serializer.save(created_by=resolve_author(kwargs.get("user")))

    def _check_secret_use(self, data: dict, *, user, org_id: int | None) -> None:
        if self.secret_use_check is None:
            return
        # Import has no request to read the actor from. Without a user there is no
        # one to hold secrets:USE, so a config with markers is denied.
        actor = SecretActor(user=user, org_id=org_id) if user is not None else None
        try:
            # Import always creates the config, so every marker and endpoint in it is new.
            self.secret_use_check(actor, None, data)
        except (SecretUseDeniedError, ModelEndpointNotSettableError) as denial:
            # Raised as a validation error, like every other rejection in this
            # strategy, so a caller handling the strategy's errors sees one kind.
            # It leaves the import's transaction, rolling it back.
            raise ValidationError(denial.field_errors()) from denial

    def export_entity(self, instance) -> dict:
        return self.serializer_class(instance).data

    def find_existing(self, data, id_mapper, org_id: int | None = None):
        data_copy = deepcopy(data)
        data_copy.pop("id", None)
        data_copy.pop("tags", None)
        data_copy.pop("org", None)

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


class BaseCatalogConfigStrategy(BaseConfigStrategy):
    """A config whose `parameters` and `connection` the model catalog governs.

    The file's values are fitted to the config's model before they are stored: settings
    the model does not take and connection fields its provider does not declare are
    dropped, and values are kept as they are. So a file from an older catalog, or an older
    export version, imports, and a second import of it reuses the config.
    """

    model_kind: ModelKind

    def find_existing(self, data, id_mapper, org_id: int | None = None):
        # As it is, the entry matches a config a catalog update made stale since the
        # export; fitted, it matches the config an earlier import of the same file created.
        return super().find_existing(data, id_mapper, org_id) or super().find_existing(
            self._fitted(data, *self._catalog_names(data, id_mapper)), id_mapper, org_id
        )

    def create_entity(self, data, id_mapper: IDMapper, **kwargs):
        provider, model_name = self._catalog_names(data, id_mapper)
        data = self._fitted(data, provider, model_name)
        ConfigValidationService().validate_import(
            provider, data["parameters"], data["connection"], kwargs.get("org_id")
        )
        return super().create_entity(data, id_mapper, **kwargs)

    def _fitted(self, data: dict, provider: str, model_name: str) -> dict:
        service = ConfigValidationService()
        parameters = data.get("parameters", {})
        connection = data.get("connection", {})
        # A part that is no object is left for validate_import to refuse.
        if isinstance(parameters, dict):
            parameters = service.drop_unsupported(self.model_kind, provider, model_name, parameters)
        if isinstance(connection, dict):
            connection = service.drop_undeclared_connection_fields(provider, connection)
        return {**data, "parameters": parameters, "connection": connection}

    def _catalog_names(self, data: dict, id_mapper: IDMapper) -> tuple[str, str]:
        """Return the provider and model name of the model row the entry maps to; empty without one."""
        model = (
            self.model_class.objects.select_related(self.provider_field)
            .filter(pk=id_mapper.get_or_none(self.model_entity_type, data.get(self.model_fk_field)))
            .first()
        )
        provider = getattr(model, self.provider_field, None)
        return (provider.name if provider else ""), (model.name if model else "")


class LLMConfigStrategy(BaseCatalogConfigStrategy):
    entity_type = EntityType.LLM_CONFIG
    model_entity_type = EntityType.LLM_MODEL
    tag_entity = EntityType.LLM_CONFIG_TAG
    config_model = LLMConfig
    serializer_class = LLMConfigImportSerializer
    model_kind = ModelKind.LLM
    secret_use_check = staticmethod(check_llm_config_write)


class EmbeddingConfigStrategy(BaseCatalogConfigStrategy):
    entity_type = EntityType.EMBEDDING_CONFIG
    model_entity_type = EntityType.EMBEDDING_MODEL
    config_model = EmbeddingConfig
    serializer_class = EmbeddingConfigImportSerializer
    model_kind = ModelKind.EMBEDDING
    secret_use_check = staticmethod(check_embedding_config_write)


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
        serializer = self.serializer_class(data={**data, "org": org_id}, context={"org_id": org_id})
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


class SystemOneConfigStrategy(BaseProviderRealtimeConfigStrategy):
    # No Secret Use check: the entity's secret never travels in a file, and it has no markers.
    entity_type = EntityType.SYSTEM_ONE_CONFIG
    config_model = SystemOneConfig
    serializer_class = SystemOneConfigImportSerializer

    def extract_dependencies_from_instance(self, instance) -> dict:
        if instance.llm_config_id is None:
            return {}
        return {EntityType.LLM_CONFIG: [instance.llm_config_id]}

    def create_entity(self, data: dict, id_mapper: IDMapper, **kwargs):
        # The file is untrusted: only an id mapped into the active org may land.
        data["llm_config"] = id_mapper.get_or_none(EntityType.LLM_CONFIG, data.get("llm_config"))
        return super().create_entity(data, id_mapper, **kwargs)

    def find_existing(self, data: dict, id_mapper: IDMapper, org_id: int | None = None):
        return (
            self.config_model.objects.filter(
                custom_name=data.get("custom_name"),
                provider=data.get("provider"),
                model_name=data.get("model_name"),
                llm_config_id=id_mapper.get_or_none(EntityType.LLM_CONFIG, data.get("llm_config")),
            )
            .filter(self.get_org_scope_q(org_id))
            .first()
        )
