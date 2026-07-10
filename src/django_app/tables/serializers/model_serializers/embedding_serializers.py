from rest_framework import serializers

from tables.models.tag_models import EmbeddingConfigTag, EmbeddingModelTag
from tables.serializers.utils.mixins import TagHandlingMixin
from tables.serializers.utils.secret_fields import SecretCharField
from tables.models.embedding_models import (
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


class EmbeddingConfigSerializer(TagHandlingMixin, serializers.ModelSerializer):
    api_key = SecretCharField(mask_style="tail")
    tags = EmbeddingConfigTagSerializer(many=True, required=False)
    tag_model = EmbeddingConfigTag

    class Meta:
        model = EmbeddingConfig
        fields = "__all__"
