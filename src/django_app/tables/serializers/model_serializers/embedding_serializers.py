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
from tables.serializers.utils.secret_reference_guard_mixin import (
    SecretReferenceGuardMixin,
    model_destination,
)
from tables.serializers.utils.soft_delete_fields import KeptLinkPrimaryKeyRelatedField
from tables.validators.model_name_validator import reject_url_in_model_name

#: EmbeddingModel fields that never affect where a request goes; see
#: LLMModelSerializer for why the list names what does NOT route.
_EMBEDDING_MODEL_NON_ROUTING_FIELDS = frozenset({"is_visible", "tags"})


class EmbeddingModelSerializer(
    AuthorSummarySerializerMixin,
    SecretReferenceGuardMixin,
    TagHandlingMixin,
    serializers.ModelSerializer,
):
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

    def get_secret_destination(self, attrs) -> dict:
        """Every writable field except the cosmetic ones: today name, embedding_provider,
        deployment and base_url. The converter and the knowledge service route on the
        first three plus the provider; `deployment` is read by nothing yet but is an
        Azure routing field by meaning, so it stays gated."""
        return self.writable_values_after_save(attrs, exclude=_EMBEDDING_MODEL_NON_ROUTING_FIELDS)

    def carries_secret_reference(self, attrs) -> bool:
        """Whether any config using this model sends its API key to where it routes.

        Not scoped to the active org, for the same reason as LLMModelSerializer.
        """
        return EmbeddingConfig.objects.filter(
            model=self.instance, api_key_secret__isnull=False
        ).exists()


class EmbeddingConfigSerializer(
    AuthorStampingSerializerMixin,
    LastEditFieldsSerializerMixin,
    SecretReferenceGuardMixin,
    TagHandlingMixin,
    serializers.ModelSerializer,
):
    secret_reference_fields = ("api_key_secret_id",)

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
        exclude = ["api_key_secret"]
        read_only_fields = ["org", "created_by", "created_at"]

    def get_secret_destination(self, attrs) -> dict:
        """The model's identity (see `model_destination`): its fields route the API key."""
        return {"model": model_destination(self.value_after_save(attrs, "model"))}

    def carries_secret_reference(self, attrs) -> bool:
        api_key_secret = self.value_after_save(
            attrs, "api_key_secret", persisted_attribute="api_key_secret_id"
        )
        return api_key_secret is not None
