from rest_framework import serializers

from tables.models.tag_models import EmbeddingConfigTag, EmbeddingModelTag
from tables.serializers.org_scoped_fields import (
    OrgScopedPrimaryKeyRelatedField,
    OrgScopedUniqueTogetherValidator,
    OrgVisiblePrimaryKeyRelatedField,
    OrgScopedUniqueValidator,
)
from tables.serializers.utils.mixins import TagHandlingMixin
from tables.models.secret_models import Secret
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
        # Explicit rather than "__all__" — see LLMModelSerializer.
        fields = [
            "id",
            "name",
            "embedding_provider",
            "deployment",
            "base_url",
            "is_visible",
            "predefined",
            "is_custom",
            "tags",
            "org",
            "created_by",
        ]
        read_only_fields = ["org", "created_by", "is_custom", "predefined"]
        validators = [
            OrgScopedUniqueTogetherValidator(
                queryset=EmbeddingModel.objects.all(),
                fields=["name", "embedding_provider"],
                message="A model with this name already exists for this provider.",
            )
        ]


class EmbeddingConfigSerializer(TagHandlingMixin, serializers.ModelSerializer):
    api_key_secret_id = OrgScopedPrimaryKeyRelatedField(
        queryset=Secret.objects.all(),
        source="api_key_secret",
        required=False,
        allow_null=True,
    )
    tags = EmbeddingConfigTagSerializer(many=True, required=False)
    tag_model = EmbeddingConfigTag
    # Org isolation (hybrid): built-in models OR the caller's active-org custom ones.
    model = OrgVisiblePrimaryKeyRelatedField(
        queryset=EmbeddingModel.objects.all(), required=False, allow_null=True
    )
    custom_name = serializers.CharField(
        validators=[
            OrgScopedUniqueValidator(
                queryset=EmbeddingConfig.objects.all(),
                message="An embedding config with this name already exists.",
            )
        ]
    )

    class Meta:
        model = EmbeddingConfig
        exclude = ["api_key_secret"]
        read_only_fields = ["org", "created_by"]
