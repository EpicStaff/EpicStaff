from rbac.authorship import (
    AuthorStampingSerializerMixin,
    AuthorSummarySerializerMixin,
    LastEditFieldsSerializerMixin,
)
from rbac.scoping.fields import (
    OrgScopedUniqueTogetherValidator,
    OrgScopedUniqueValidator,
    OrgVisiblePrimaryKeyRelatedField,
)
from rest_framework import serializers
from tables.models.secret_models import Secret
from tables.serializers.utils.mixins import TagHandlingMixin
from tables.serializers.utils.soft_delete_fields import KeptLinkPrimaryKeyRelatedField
from tables.validators.extra_headers_validator import validate_extra_headers

from ai_models.domain.specs import ModelKind
from ai_models.models import EmbeddingConfig, EmbeddingConfigTag, EmbeddingModel, EmbeddingModelTag
from ai_models.serializers.model_serializers.tag_serializers import (
    EmbeddingConfigTagSerializer,
    EmbeddingTagSerializer,
)
from ai_models.serializers.utils.catalog_config_fields import (
    REMOVED_MODEL_FIELDS,
    CatalogConfigFieldsMixin,
    reject_removed_fields,
)


class EmbeddingModelSerializer(
    AuthorSummarySerializerMixin, TagHandlingMixin, serializers.ModelSerializer
):
    tags = EmbeddingTagSerializer(many=True, required=False)
    tag_model = EmbeddingModelTag

    class Meta:
        model = EmbeddingModel
        fields = [
            "id",
            "name",
            "embedding_provider",
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

    def to_internal_value(self, data):
        reject_removed_fields(data, REMOVED_MODEL_FIELDS)
        return super().to_internal_value(data)


class EmbeddingConfigSerializer(
    CatalogConfigFieldsMixin,
    AuthorStampingSerializerMixin,
    LastEditFieldsSerializerMixin,
    TagHandlingMixin,
    serializers.ModelSerializer,
):
    api_key_secret_id = KeptLinkPrimaryKeyRelatedField(
        queryset=Secret.all_objects.all(),
        source="api_key_secret",
        required=False,
        allow_null=True,
    )
    tags = EmbeddingConfigTagSerializer(many=True, required=False)
    tag_model = EmbeddingConfigTag
    model_kind = ModelKind.EMBEDDING
    provider_field = "embedding_provider"
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
        read_only_fields = ["org", "created_by", "created_at"]
        extra_kwargs = {"extra_headers": {"validators": [validate_extra_headers]}}
