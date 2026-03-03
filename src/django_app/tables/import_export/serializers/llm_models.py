from rest_framework import serializers

from tables.models import (
    LLMModel,
    EmbeddingModel,
    RealtimeModel,
    RealtimeTranscriptionModel,
    Provider,
)


class BaseModelImportSerializer(serializers.ModelSerializer):
    provider_field = None

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if cls.provider_field:
            cls.provider_id = serializers.PrimaryKeyRelatedField(
                queryset=Provider.objects.all(),
                source=cls.provider_field,
                write_only=True,
            )

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        ret["provider_name"] = getattr(instance, self.provider_field).name
        return ret


class LLMModelImportSerializer(BaseModelImportSerializer):
    provider_field = "llm_provider"
    provider_id = serializers.PrimaryKeyRelatedField(
        queryset=Provider.objects.all(),
        source="llm_provider",
        write_only=True,
    )

    class Meta:
        model = LLMModel
        exclude = ["llm_provider"]


class EmbeddingModelImportSerializer(BaseModelImportSerializer):
    provider_field = "embedding_provider"
    provider_id = serializers.PrimaryKeyRelatedField(
        queryset=Provider.objects.all(),
        source="embedding_provider",
        write_only=True,
    )

    class Meta:
        model = EmbeddingModel
        exclude = ["embedding_provider"]


class RealtimeModelImportSerializer(BaseModelImportSerializer):
    provider_field = "provider"
    provider_id = serializers.PrimaryKeyRelatedField(
        queryset=Provider.objects.all(),
        source="provider",
        write_only=True,
    )

    class Meta:
        model = RealtimeModel
        exclude = ["provider"]


class RealtimeTranscriptionModelImportSerializer(BaseModelImportSerializer):
    provider_field = "provider"
    provider_id = serializers.PrimaryKeyRelatedField(
        queryset=Provider.objects.all(),
        source="provider",
        write_only=True,
    )

    class Meta:
        model = RealtimeTranscriptionModel
        exclude = ["provider"]
