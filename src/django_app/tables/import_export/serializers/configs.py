from rest_framework import serializers

from tables.models import (
    LLMConfig,
    LLMModel,
    EmbeddingModel,
    EmbeddingConfig,
    RealtimeModel,
    RealtimeConfig,
    RealtimeTranscriptionModel,
    RealtimeTranscriptionConfig,
)
from tables.models.realtime_models import (
    OpenAIRealtimeConfig,
    ElevenLabsRealtimeConfig,
    GeminiRealtimeConfig,
)


class BaseConfigImportSerializer(serializers.ModelSerializer):
    api_key = serializers.CharField(write_only=True, required=False)

    model_class = None
    provider_field = None
    config_model = None
    model_fk_field = None

    class Meta:
        abstract = True
        model = None
        exclude = ["created_by"]

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


class EmbeddingConfigImportSerializer(BaseConfigImportSerializer):
    model_class = EmbeddingModel
    provider_field = "embedding_provider"
    model_fk_field = "model"
    config_model = EmbeddingConfig

    embedding_model = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta(BaseConfigImportSerializer.Meta):
        model = EmbeddingConfig


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


class OpenAIRealtimeConfigImportSerializer(serializers.ModelSerializer):
    api_key = serializers.CharField(
        write_only=True, required=False, allow_null=True, allow_blank=True
    )
    transcription_api_key = serializers.CharField(
        write_only=True, required=False, allow_null=True, allow_blank=True
    )

    class Meta:
        model = OpenAIRealtimeConfig
        fields = "__all__"

    def create(self, validated_data):
        org = validated_data.get("org")
        if not validated_data.get("api_key"):
            validated_data["api_key"] = (
                OpenAIRealtimeConfig.objects.filter(org=org)
                .values_list("api_key", flat=True)
                .first()
            )
        if not validated_data.get("transcription_api_key"):
            validated_data["transcription_api_key"] = (
                OpenAIRealtimeConfig.objects.filter(org=org)
                .values_list("transcription_api_key", flat=True)
                .first()
            )
        return super().create(validated_data)


class ElevenLabsRealtimeConfigImportSerializer(serializers.ModelSerializer):
    api_key = serializers.CharField(
        write_only=True, required=False, allow_null=True, allow_blank=True
    )

    class Meta:
        model = ElevenLabsRealtimeConfig
        fields = "__all__"

    def create(self, validated_data):
        org = validated_data.get("org")
        if not validated_data.get("api_key"):
            validated_data["api_key"] = (
                ElevenLabsRealtimeConfig.objects.filter(org=org)
                .values_list("api_key", flat=True)
                .first()
            )
        return super().create(validated_data)


class GeminiRealtimeConfigImportSerializer(serializers.ModelSerializer):
    api_key = serializers.CharField(
        write_only=True, required=False, allow_null=True, allow_blank=True
    )

    class Meta:
        model = GeminiRealtimeConfig
        fields = "__all__"

    def create(self, validated_data):
        org = validated_data.get("org")
        if not validated_data.get("api_key"):
            validated_data["api_key"] = (
                GeminiRealtimeConfig.objects.filter(org=org)
                .values_list("api_key", flat=True)
                .first()
            )
        return super().create(validated_data)
