from rest_framework import serializers

from tables.models import (
    Provider,
    LLMConfig,
    LLMModel,
    EmbeddingModel,
    EmbeddingConfig,
    RealtimeModel,
    RealtimeConfig,
    RealtimeTranscriptionModel,
    RealtimeTranscriptionConfig,
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
        fields = "__all__"

    def get_fields(self):
        fields = super().get_fields()
        if self.model_class and self.model_fk_field:
            fields["model_id"] = serializers.PrimaryKeyRelatedField(
                queryset=self.model_class.objects.all(),
                source=self.model_fk_field,
                write_only=True,
            )
        return fields

    def create(self, validated_data):
        model = validated_data[self.model_fk_field]
        validated_data["api_key"] = self._get_api_key(
            getattr(model, self.provider_field).name
        )

        return super().create(validated_data)

    def _get_api_key(self, provider_name):
        return (
            self.config_model.objects.filter(
                **{f"{self.model_fk_field}__{self.provider_field}__name": provider_name}
            )
            .values_list("api_key", flat=True)
            .first()
        )


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
