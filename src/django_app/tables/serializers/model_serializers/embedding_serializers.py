from rest_framework import serializers

from tables.models.tag_models import EmbeddingConfigTag, EmbeddingModelTag
from tables.serializers.org_scoped_fields import (
    OrgVisiblePrimaryKeyRelatedField,
    OrgScopedUniqueValidator,
)
from tables.serializers.utils.mixins import TagHandlingMixin
from tables.serializers.utils.secret_fields import (
    MaskedSecretField,
    SecretFieldWriteMixin,
)
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
        read_only_fields = ["org", "created_by"]


class EmbeddingConfigSerializer(
    SecretFieldWriteMixin, TagHandlingMixin, serializers.ModelSerializer
):
    secret_fk_fields = ["api_key_secret"]
    api_key = MaskedSecretField(source="api_key_secret")
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
