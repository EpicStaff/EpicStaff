from rest_framework import serializers

from tables.models.tag_models import EmbeddingConfigTag, EmbeddingModelTag
from tables.serializers.utils.mixins import TagHandlingMixin
from tables.models.embedding_models import (
    DefaultEmbeddingConfig,
    EmbeddingConfig,
    EmbeddingModel,
)

from tables.serializers.model_serializers.tag_serializers import (
    EmbeddingConfigTagSerializer,
    EmbeddingTagSerializer,
)


class EmbeddingModelSerializer(TagHandlingMixin, serializers.ModelSerializer):
    tags = EmbeddingTagSerializer(many=True, required=False)
    tag_model = EmbeddingModelTag

    class Meta:
        model = EmbeddingModel
        fields = "__all__"
        read_only_fields = ["org", "created_by"]


class EmbeddingConfigSerializer(TagHandlingMixin, serializers.ModelSerializer):
    tags = EmbeddingConfigTagSerializer(many=True, required=False)
    tag_model = EmbeddingConfigTag

    class Meta:
        model = EmbeddingConfig
        fields = "__all__"
        read_only_fields = ["org", "created_by"]


class DefaultEmbeddingConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = DefaultEmbeddingConfig
        fields = [
            "model",
            "task_type",
            "api_key",
        ]
