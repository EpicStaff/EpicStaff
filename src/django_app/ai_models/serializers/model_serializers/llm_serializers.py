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
from tables.validators.token_price_validator import validate_token_prices_set_together

from ai_models.domain.specs import ModelKind
from ai_models.models import LLMConfig, LLMConfigTag, LLMModel, LLMModelTag
from ai_models.serializers.model_serializers.tag_serializers import (
    LLMConfigTagSerializer,
    LLMModelTagSerializer,
)
from ai_models.serializers.utils.catalog_config_fields import (
    REMOVED_MODEL_FIELDS,
    CatalogConfigFieldsMixin,
    reject_removed_fields,
)
from ai_models.utils.litellm_model_info import model_reasoning_support


class LLMConfigSerializer(
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
    tags = LLMConfigTagSerializer(many=True, required=False)
    tag_model = LLMConfigTag
    model_kind = ModelKind.LLM
    provider_field = "llm_provider"
    # Org isolation (hybrid): built-in models OR the caller's active-org custom ones.
    model = OrgVisiblePrimaryKeyRelatedField(
        queryset=LLMModel.objects.all(), required=False, allow_null=True
    )
    custom_name = serializers.CharField(
        validators=[
            OrgScopedUniqueValidator(
                queryset=LLMConfig.objects.all(),
                message="An LLM config with this name already exists.",
            )
        ]
    )

    class Meta:
        model = LLMConfig
        exclude = ["api_key_secret"]
        read_only_fields = ["org", "created_by", "created_at"]
        extra_kwargs = {"extra_headers": {"validators": [validate_extra_headers]}}

    def validate(self, attrs):
        attrs = super().validate(attrs)
        # A PATCH may send one price; the other one is then the stored value.
        validate_token_prices_set_together(
            attrs.get("input_cost_per_token", getattr(self.instance, "input_cost_per_token", None)),
            attrs.get(
                "output_cost_per_token", getattr(self.instance, "output_cost_per_token", None)
            ),
        )
        return attrs


class LLMModelSerializer(
    AuthorSummarySerializerMixin, TagHandlingMixin, serializers.ModelSerializer
):
    capabilities = LLMModelTagSerializer(source="tags", many=True, required=False)
    tag_model = LLMModelTag
    supports_reasoning = serializers.SerializerMethodField()
    reasoning_efforts = serializers.SerializerMethodField()

    class Meta:
        model = LLMModel
        fields = [
            "id",
            "name",
            "llm_provider",
            "description",
            "is_visible",
            "predefined",
            "is_custom",
            "capabilities",
            "tags",
            "org",
            "created_by",
            "supports_reasoning",
            "reasoning_efforts",
        ]
        read_only_fields = ["org", "created_by", "is_custom", "predefined"]
        validators = [
            OrgScopedUniqueTogetherValidator(
                queryset=LLMModel.objects.all(),
                fields=["name", "llm_provider"],
                message="A model with this name already exists for this provider.",
            )
        ]

    def to_internal_value(self, data):
        reject_removed_fields(data, REMOVED_MODEL_FIELDS)
        return super().to_internal_value(data)

    def get_supports_reasoning(self, model: LLMModel) -> bool:
        return model_reasoning_support(model).supports_reasoning

    def get_reasoning_efforts(self, model: LLMModel) -> list[str]:
        return model_reasoning_support(model).ordered_efforts()
