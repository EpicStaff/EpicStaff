from rest_framework import serializers

from tables.models.secret_models import Secret

from tables.serializers.model_serializers.tag_serializers import (
    LLMConfigTagSerializer,
    LLMModelTagSerializer,
)
from tables.models.llm_models import (
    LLMConfig,
    LLMModel,
    RealtimeModel,
    RealtimeConfig,
    RealtimeTranscriptionModel,
    RealtimeTranscriptionConfig,
)
from tables.models.tag_models import LLMConfigTag, LLMModelTag
from tables.serializers.org_scoped_fields import (
    OrgScopedPrimaryKeyRelatedField,
    OrgScopedUniqueTogetherValidator,
    OrgVisiblePrimaryKeyRelatedField,
    OrgScopedUniqueValidator,
)


from ..utils.mixins import TagHandlingMixin


class RealtimeModelSerializer(serializers.ModelSerializer):
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


class RealtimeConfigSerializer(serializers.ModelSerializer):
    api_key_secret_id = OrgScopedPrimaryKeyRelatedField(
        queryset=Secret.objects.all(),
        source="api_key_secret",
        required=False,
        allow_null=True,
    )
    provider_name = serializers.CharField(
        source="realtime_model.provider.name", read_only=True
    )
    # Org isolation (hybrid): built-in models OR the caller's active-org custom ones.
    realtime_model = OrgVisiblePrimaryKeyRelatedField(
        queryset=RealtimeModel.objects.all()
    )

    class Meta:
        model = RealtimeConfig
        exclude = ["api_key_secret"]
        read_only_fields = ["org", "created_by"]


class RealtimeTranscriptionModelSerializer(serializers.ModelSerializer):
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


class RealtimeTranscriptionConfigSerializer(serializers.ModelSerializer):
    api_key_secret_id = OrgScopedPrimaryKeyRelatedField(
        queryset=Secret.objects.all(),
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


class LLMConfigSerializer(TagHandlingMixin, serializers.ModelSerializer):
    api_key_secret_id = OrgScopedPrimaryKeyRelatedField(
        queryset=Secret.objects.all(),
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
        read_only_fields = ["org", "created_by"]


class LLMModelSerializer(TagHandlingMixin, serializers.ModelSerializer):
    capabilities = LLMModelTagSerializer(source="tags", many=True, required=False)
    tag_model = LLMModelTag

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
        ]
        read_only_fields = ["org", "created_by", "is_custom", "predefined"]
        validators = [
            OrgScopedUniqueTogetherValidator(
                queryset=LLMModel.objects.all(),
                fields=["name", "llm_provider"],
                message="A model with this name already exists for this provider.",
            )
        ]
