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
from tables.models.llm_models import (
    LLMConfig,
    LLMModel,
    RealtimeConfig,
    RealtimeModel,
    RealtimeTranscriptionConfig,
    RealtimeTranscriptionModel,
)
from tables.models.secret_models import Secret
from tables.models.tag_models import LLMConfigTag, LLMModelTag
from tables.serializers.model_serializers.tag_serializers import (
    LLMConfigTagSerializer,
    LLMModelTagSerializer,
)
from tables.serializers.utils.soft_delete_fields import KeptLinkPrimaryKeyRelatedField
from tables.utils.litellm_model_info import model_reasoning_support, validate_reasoning_effort

from ..utils.llm_config_data_validation import LLMConfigDataFieldsValidationMixin
from ..utils.mixins import TagHandlingMixin
from ..utils.secret_destination_guard_mixin import (
    LLM_MODEL_ENDPOINT_FIELDS,
    SecretDestinationGuardMixin,
)
from ..utils.secret_reference_guard_mixin import SecretReferenceGuardMixin


class RealtimeModelSerializer(AuthorSummarySerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = RealtimeModel
        fields = ["id", "name", "provider", "is_custom", "org", "created_by"]
        read_only_fields = ["org", "created_by", "is_custom"]
        validators = [
            OrgScopedUniqueTogetherValidator(
                queryset=RealtimeModel.objects.all(),
                fields=["name", "provider"],
                message="A model with this name already exists for this provider.",
            )
        ]


class RealtimeConfigSerializer(
    AuthorSummarySerializerMixin, SecretReferenceGuardMixin, serializers.ModelSerializer
):
    secret_reference_fields = ("api_key_secret_id",)

    api_key_secret_id = KeptLinkPrimaryKeyRelatedField(
        queryset=Secret.all_objects.all(),
        source="api_key_secret",
        required=False,
        allow_null=True,
    )
    provider_name = serializers.CharField(source="realtime_model.provider.name", read_only=True)
    # Org isolation (hybrid): built-in models OR the caller's active-org custom ones.
    realtime_model = OrgVisiblePrimaryKeyRelatedField(queryset=RealtimeModel.objects.all())

    class Meta:
        model = RealtimeConfig
        exclude = ["api_key_secret"]
        read_only_fields = ["org", "created_by"]


class RealtimeTranscriptionModelSerializer(
    AuthorSummarySerializerMixin, serializers.ModelSerializer
):
    class Meta:
        model = RealtimeTranscriptionModel
        fields = ["id", "name", "provider", "is_custom", "org", "created_by"]
        read_only_fields = ["org", "created_by", "is_custom"]
        validators = [
            OrgScopedUniqueTogetherValidator(
                queryset=RealtimeTranscriptionModel.objects.all(),
                fields=["name", "provider"],
                message="A model with this name already exists for this provider.",
            )
        ]


class RealtimeTranscriptionConfigSerializer(
    AuthorSummarySerializerMixin, SecretReferenceGuardMixin, serializers.ModelSerializer
):
    secret_reference_fields = ("api_key_secret_id",)

    api_key_secret_id = KeptLinkPrimaryKeyRelatedField(
        queryset=Secret.all_objects.all(),
        source="api_key_secret",
        required=False,
        allow_null=True,
    )
    # Org isolation (hybrid): built-in models OR the caller's active-org custom ones.
    realtime_transcription_model = OrgVisiblePrimaryKeyRelatedField(
        queryset=RealtimeTranscriptionModel.objects.all()
    )

    class Meta:
        model = RealtimeTranscriptionConfig
        exclude = ["api_key_secret"]
        read_only_fields = ["org", "created_by"]


class LLMConfigSerializer(
    LLMConfigDataFieldsValidationMixin,
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
    tags = LLMConfigTagSerializer(many=True, required=False)
    tag_model = LLMConfigTag
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

    def validate(self, attrs):
        """Reject a reasoning effort the effective model cannot take.

        Checked only when the request touches `model` or `reasoning_effort`, so
        editing another field of a config never fails because litellm's model map
        changed since the config was saved.
        """
        attrs = super().validate(attrs)
        if "model" not in attrs and "reasoning_effort" not in attrs:
            return attrs

        model = attrs.get("model", self.instance.model if self.instance else None)
        reasoning_effort = attrs.get(
            "reasoning_effort", self.instance.reasoning_effort if self.instance else None
        )
        validate_reasoning_effort(model, reasoning_effort)
        return attrs


class LLMModelSerializer(
    AuthorSummarySerializerMixin,
    SecretDestinationGuardMixin,
    TagHandlingMixin,
    serializers.ModelSerializer,
):
    secret_destination_fields = LLM_MODEL_ENDPOINT_FIELDS

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
            "deployment_id",
            "api_version",
            "base_url",
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

    def get_supports_reasoning(self, model: LLMModel) -> bool:
        return model_reasoning_support(model).supports_reasoning

    def get_reasoning_efforts(self, model: LLMModel) -> list[str]:
        return model_reasoning_support(model).ordered_efforts()
