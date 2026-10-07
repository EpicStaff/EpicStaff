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
)
from tables.models.realtime_models import (
    ElevenLabsRealtimeConfig,
    GeminiRealtimeConfig,
    OpenAIRealtimeConfig,
)
from tables.serializers.base_serializer import OpenAIRealtimeModelNameValidationMixin


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


class LLMConfigImportSerializer(BaseConfigImportSerializer):
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
