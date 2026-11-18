from rest_framework import serializers

from tables.models import (
    EmbeddingConfig,
    EmbeddingModel,
    LLMConfig,
    LLMModel,
    RealtimeConfig,
    RealtimeModel,
    RealtimeTranscriptionConfig,
    RealtimeTranscriptionModel,
    SystemOneConfig,
)
from tables.models.realtime_models import (
    ElevenLabsRealtimeConfig,
    GeminiRealtimeConfig,
    OpenAIRealtimeConfig,
)
from tables.serializers.base_serializer import OpenAIRealtimeModelNameValidationMixin
from tables.serializers.model_serializers.llm_serializers import (
    SYSTEM_ONE_FORBIDDEN_FIELDS,
    system_one_model_error,
)
from tables.serializers.utils.llm_config_data_validation import (
    LLMConfigDataFieldsValidationMixin,
)
from tables.utils.litellm_model_info import validate_reasoning_effort
from tables.validators.extra_headers_validator import validate_extra_headers
from tables.validators.token_price_validator import validate_token_prices_set_together


class BaseConfigImportSerializer(serializers.ModelSerializer):
    model_class = None
    provider_field = None
    config_model = None
    model_fk_field = None

    class Meta:
        abstract = True
        model = None
        exclude = ["created_by", "api_key_secret"]

    def get_fields(self):
        fields = super().get_fields()
        if self.model_class and self.model_fk_field:
            fields["model_id"] = serializers.PrimaryKeyRelatedField(
                queryset=self.model_class.objects.all(),
                source=self.model_fk_field,
                write_only=True,
            )
        return fields


class LLMConfigImportSerializer(LLMConfigDataFieldsValidationMixin, BaseConfigImportSerializer):
    model_class = LLMModel
    provider_field = "llm_provider"
    model_fk_field = "model"
    config_model = LLMConfig

    model = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta(BaseConfigImportSerializer.Meta):
        model = LLMConfig
        # Keep created_at out of the export: BaseConfigStrategy.find_existing filters on
        # every exported key, and an equivalent config created by an earlier import has
        # its own creation time, so re-imports would stop matching it and duplicate it.
        exclude = [*BaseConfigImportSerializer.Meta.exclude, "created_at"]
        extra_kwargs = {"extra_headers": {"validators": [validate_extra_headers]}}

    def validate(self, attrs):
        attrs = super().validate(attrs)
        validate_token_prices_set_together(
            attrs.get("input_cost_per_token"), attrs.get("output_cost_per_token")
        )
        validate_reasoning_effort(attrs.get("model"), attrs.get("reasoning_effort"))
        return attrs


class EmbeddingConfigImportSerializer(BaseConfigImportSerializer):
    model_class = EmbeddingModel
    provider_field = "embedding_provider"
    model_fk_field = "model"
    config_model = EmbeddingConfig

    embedding_model = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta(BaseConfigImportSerializer.Meta):
        model = EmbeddingConfig
        # Keep created_at out of the export: BaseConfigStrategy.find_existing filters on
        # every exported key, and an equivalent config created by an earlier import has
        # its own creation time, so re-imports would stop matching it and duplicate it.
        exclude = [*BaseConfigImportSerializer.Meta.exclude, "created_at"]
        extra_kwargs = {"extra_headers": {"validators": [validate_extra_headers]}}


class RealtimeConfigImportSerializer(BaseConfigImportSerializer):
    model_class = RealtimeModel
    provider_field = "provider"
    model_fk_field = "realtime_model"
    config_model = RealtimeConfig

    realtime_model = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta(BaseConfigImportSerializer.Meta):
        model = RealtimeConfig


class RealtimeTranscriptionConfigImportSerializer(BaseConfigImportSerializer):
    model_class = RealtimeTranscriptionModel
    provider_field = "provider"
    model_fk_field = "realtime_transcription_model"
    config_model = RealtimeTranscriptionConfig

    realtime_transcription_model = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta(BaseConfigImportSerializer.Meta):
        model = RealtimeTranscriptionConfig


# The provider realtime config serializers below keep created_at out of the export, as
# LLMConfig does: the import never writes it (it is auto_now_add), so exporting it would
# only carry the source config's creation time into the file.
class OpenAIRealtimeConfigImportSerializer(
    OpenAIRealtimeModelNameValidationMixin, serializers.ModelSerializer
):
    """Secrets never travel through import/export -- same convention as
    BaseConfigImportSerializer's `exclude = [..., "api_key_secret"]` for
    LLMConfig/EmbeddingConfig. The imported config lands with no key; the
    destination org's admin must assign one after import."""

    class Meta:
        model = OpenAIRealtimeConfig
        exclude = [
            "created_by",
            "created_at",
            "api_key_secret",
            "transcription_api_key_secret",
        ]


class ElevenLabsRealtimeConfigImportSerializer(serializers.ModelSerializer):
    class Meta:
        model = ElevenLabsRealtimeConfig
        exclude = ["created_by", "created_at", "api_key_secret"]


class GeminiRealtimeConfigImportSerializer(serializers.ModelSerializer):
    class Meta:
        model = GeminiRealtimeConfig
        exclude = ["created_by", "created_at", "api_key_secret"]


class SystemOneConfigImportSerializer(serializers.ModelSerializer):
    """Secrets never travel through import/export. An imported TypeSafe or OpenAI config
    lands with no key; the destination org's admin must assign one after import."""

    model_name = serializers.CharField(max_length=64, required=False, allow_null=True)

    class Meta:
        model = SystemOneConfig
        exclude = ["created_by", "created_at", "api_key_secret"]

    def validate(self, attrs):
        # The database forbids the other provider's fields, and DRF does not run
        # check constraints: reject them here so a crafted file is a 400, not a 500.
        # Required fields are not checked: an imported config has no key.
        errors = {
            field: message
            for field, message in SYSTEM_ONE_FORBIDDEN_FIELDS[attrs["provider"]].items()
            if attrs.get(field) is not None
        }
        model_error = system_one_model_error(attrs["provider"], attrs.get("model_name"))
        if model_error:
            errors["model_name"] = model_error
        if errors:
            raise serializers.ValidationError(errors)
        return attrs
