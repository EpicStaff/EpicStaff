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
from tables.models.embedding_models import (
    EmbeddingConfig,
    EmbeddingModel,
)
from tables.models.secret_models import Secret
from tables.models.tag_models import EmbeddingConfigTag, EmbeddingModelTag
from tables.serializers.model_serializers.tag_serializers import (
    EmbeddingConfigTagSerializer,
    EmbeddingTagSerializer,
)
from tables.serializers.utils.mixins import TagHandlingMixin
from tables.serializers.utils.secret_reference_guard_mixin import SecretReferenceGuardMixin
from tables.serializers.utils.soft_delete_fields import KeptLinkPrimaryKeyRelatedField
from tables.services.secrets.policies import (
    EMBEDDING_CONFIG_SECRET_POLICY,
    EMBEDDING_MODEL_SECRET_POLICY,
)
from tables.validators.extra_headers_validator import validate_extra_headers
from tables.validators.model_name_validator import reject_url_in_model_name


class EmbeddingModelSerializer(
    AuthorSummarySerializerMixin,
    SecretReferenceGuardMixin,
    TagHandlingMixin,
    serializers.ModelSerializer,
):
    secret_policy = EMBEDDING_MODEL_SECRET_POLICY

    tags = EmbeddingTagSerializer(many=True, required=False)
    tag_model = EmbeddingModelTag

    class Meta:
        model = EmbeddingModel
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
        extra_kwargs = {"name": {"validators": [reject_url_in_model_name]}}
        validators = [
            OrgScopedUniqueTogetherValidator(
                queryset=EmbeddingModel.objects.all(),
                fields=["name", "embedding_provider"],
                message="A model with this name already exists for this provider.",
            )
        ]


class EmbeddingConfigSerializer(
    AuthorStampingSerializerMixin,
    LastEditFieldsSerializerMixin,
    SecretReferenceGuardMixin,
    TagHandlingMixin,
    serializers.ModelSerializer,
):
    secret_policy = EMBEDDING_CONFIG_SECRET_POLICY
    secret_marker_fields = ("extra_headers",)

    api_key_secret_id = KeptLinkPrimaryKeyRelatedField(
        queryset=Secret.all_objects.all(),
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
        exclude = ["api_key_secret", "secret_binding_approved_by"]
        read_only_fields = ["org", "created_by", "created_at"]
        extra_kwargs = {"extra_headers": {"validators": [validate_extra_headers]}}
