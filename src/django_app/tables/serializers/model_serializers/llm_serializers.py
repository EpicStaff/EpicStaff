from rbac.authorship import (
    AuthorStampingSerializerMixin,
    AuthorSummarySerializerMixin,
    LastEditFieldsSerializerMixin,
)
from rbac.scoping.fields import (
    OrgScopedPrimaryKeyRelatedField,
    OrgScopedUniqueTogetherValidator,
    OrgScopedUniqueValidator,
    OrgVisiblePrimaryKeyRelatedField,
)
from rest_framework import serializers
from src.shared.system_one.constants import (
    LLM_PROVIDER,
    OPENAI_PROVIDER,
    SYSTEM_ONE_MODELS_BY_PROVIDER,
    TYPESAFE_PROVIDER,
)
from tables.models.llm_models import (
    LLM_CONFIG_TIMEOUT_MAX_SECONDS,
    LLMConfig,
    LLMModel,
    RealtimeConfig,
    RealtimeModel,
    RealtimeTranscriptionConfig,
    RealtimeTranscriptionModel,
    SystemOneConfig,
)
from tables.models.secret_models import Secret
from tables.models.tag_models import LLMConfigTag, LLMModelTag
from tables.serializers.model_serializers.tag_serializers import (
    LLMConfigTagSerializer,
    LLMModelTagSerializer,
)
from tables.serializers.utils.soft_delete_fields import KeptLinkPrimaryKeyRelatedField
from tables.utils.litellm_model_info import model_reasoning_support, validate_reasoning_effort
from tables.validators.extra_headers_validator import validate_extra_headers
from tables.validators.token_price_validator import validate_token_prices_set_together

from ..utils.llm_config_data_validation import LLMConfigDataFieldsValidationMixin
from ..utils.mixins import TagHandlingMixin


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


class RealtimeConfigSerializer(AuthorSummarySerializerMixin, serializers.ModelSerializer):
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
    AuthorSummarySerializerMixin, serializers.ModelSerializer
):
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
        extra_kwargs = {
            "extra_headers": {"validators": [validate_extra_headers]},
            "timeout": {"max_value": LLM_CONFIG_TIMEOUT_MAX_SECONDS},
        }

    def validate(self, attrs):
        attrs = super().validate(attrs)
        # A PATCH may send one price; the other one is then the stored value.
        validate_token_prices_set_together(
            attrs.get("input_cost_per_token", getattr(self.instance, "input_cost_per_token", None)),
            attrs.get(
                "output_cost_per_token", getattr(self.instance, "output_cost_per_token", None)
            ),
        )
        return self._validate_reasoning_effort(attrs)

    def _validate_reasoning_effort(self, attrs):
        """Reject a reasoning effort the effective model cannot take.

        Checked only when the request touches `model` or `reasoning_effort`, so
        editing another field of a config never fails because litellm's model map
        changed since the config was saved.
        """
        if "model" not in attrs and "reasoning_effort" not in attrs:
            return attrs

        model = attrs.get("model", self.instance.model if self.instance else None)
        reasoning_effort = attrs.get(
            "reasoning_effort", self.instance.reasoning_effort if self.instance else None
        )
        validate_reasoning_effort(model, reasoning_effort)
        return attrs


class LLMConfigTimeoutLimitsSerializer(serializers.Serializer):
    min_seconds = serializers.IntegerField(read_only=True)
    max_seconds = serializers.IntegerField(
        read_only=True, help_text="Largest timeout an LLM config may be saved with."
    )


# Field name -> message, per provider. Names are the API names; `api_key_secret_id`
# is read from `attrs["api_key_secret"]`.
_SYSTEM_ONE_REQUIRED_FIELDS = {
    TYPESAFE_PROVIDER: {
        "model_name": "Pick a Jev version.",
        "api_key_secret_id": "A TypeSafe config needs an API key secret.",
    },
    OPENAI_PROVIDER: {
        "model_name": "Pick an OpenAI Decisions model.",
        "api_key_secret_id": "An OpenAI config needs an API key secret.",
    },
    LLM_PROVIDER: {"llm_config": "An LLM-backed config needs an LLM config."},
}
SYSTEM_ONE_FORBIDDEN_FIELDS = {
    TYPESAFE_PROVIDER: {"llm_config": "A TypeSafe config does not use an LLM config."},
    OPENAI_PROVIDER: {"llm_config": "An OpenAI config does not use an LLM config."},
    LLM_PROVIDER: {
        "model_name": "An LLM-backed config has no model name.",
        "api_key_secret_id": "An LLM-backed config has no API key secret.",
    },
}
_SYSTEM_ONE_ATTRIBUTE_BY_FIELD = {"api_key_secret_id": "api_key_secret"}


def system_one_model_error(provider: str, model_name: str | None) -> str | None:
    """Return the error for a `model_name` the provider does not offer, else None.

    Only key-bearing providers (those with a model list) are checked; an LLM-backed
    config's `model_name` is refused by SYSTEM_ONE_FORBIDDEN_FIELDS instead.
    """
    if provider not in SYSTEM_ONE_MODELS_BY_PROVIDER or model_name is None:
        return None
    if model_name in SYSTEM_ONE_MODELS_BY_PROVIDER[provider]:
        return None
    return _SYSTEM_ONE_REQUIRED_FIELDS[provider]["model_name"]


class SystemOneConfigSerializer(
    AuthorStampingSerializerMixin,
    LastEditFieldsSerializerMixin,
    serializers.ModelSerializer,
):
    api_key_secret_id = KeptLinkPrimaryKeyRelatedField(
        queryset=Secret.all_objects.all(),
        source="api_key_secret",
        required=False,
        allow_null=True,
    )
    llm_config = OrgScopedPrimaryKeyRelatedField(
        queryset=LLMConfig.objects.all(), required=False, allow_null=True
    )
    model_name = serializers.CharField(max_length=64, required=False, allow_null=True)
    custom_name = serializers.CharField(
        validators=[
            OrgScopedUniqueValidator(
                queryset=SystemOneConfig.objects.all(),
                message="A System One config with this name already exists.",
            )
        ]
    )

    class Meta:
        model = SystemOneConfig
        fields = [
            "id",
            "custom_name",
            "provider",
            "model_name",
            "api_key_secret_id",
            "llm_config",
            "org",
            "created_by",
            "created_at",
        ]
        read_only_fields = ["org", "created_by", "created_at"]

    def validate(self, attrs):
        attrs = super().validate(attrs)
        provider = self._effective(attrs, "provider")
        errors = {}
        for field, message in SYSTEM_ONE_FORBIDDEN_FIELDS[provider].items():
            if self._effective(attrs, field) is not None:
                errors[field] = message
        for field, message in _SYSTEM_ONE_REQUIRED_FIELDS[provider].items():
            if self._effective(attrs, field) is None:
                errors[field] = message
        model_error = system_one_model_error(provider, self._effective(attrs, "model_name"))
        if model_error:
            errors["model_name"] = model_error
        if errors:
            raise serializers.ValidationError(errors)
        return attrs

    def _effective(self, attrs, field):
        """The value after this write: sent in `attrs`, else the stored one (a PATCH may send one field)."""
        attribute = _SYSTEM_ONE_ATTRIBUTE_BY_FIELD.get(field, field)
        if attribute in attrs:
            return attrs[attribute]
        return getattr(self.instance, attribute, None)


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
