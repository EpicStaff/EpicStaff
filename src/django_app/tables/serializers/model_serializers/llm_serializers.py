from tables.serializers.utils.secret_fields import (
    MaskedSecretField,
    SecretFieldWriteMixin,
)
from rest_framework import serializers

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
    OrgVisiblePrimaryKeyRelatedField,
    OrgScopedUniqueValidator,
)


from ..utils.mixins import TagHandlingMixin


class RealtimeModelSerializer(serializers.ModelSerializer):
    class Meta:
        model = RealtimeModel
        fields = "__all__"
        read_only_fields = ["org", "created_by"]


class RealtimeConfigSerializer(SecretFieldWriteMixin, serializers.ModelSerializer):
    secret_fk_fields = ["api_key_secret"]
    api_key = MaskedSecretField(source="api_key_secret")
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
        fields = "__all__"
        read_only_fields = ["org", "created_by"]


class RealtimeTranscriptionConfigSerializer(
    SecretFieldWriteMixin, serializers.ModelSerializer
):
    secret_fk_fields = ["api_key_secret"]
    api_key = MaskedSecretField(source="api_key_secret")
    # Org isolation (hybrid): built-in models OR the caller's active-org custom ones.
    realtime_transcription_model = OrgVisiblePrimaryKeyRelatedField(
        queryset=RealtimeTranscriptionModel.objects.all()
    )

    class Meta:
        model = RealtimeTranscriptionConfig
        exclude = ["api_key_secret"]
        read_only_fields = ["org", "created_by"]


class LLMConfigSerializer(
    SecretFieldWriteMixin, TagHandlingMixin, serializers.ModelSerializer
):
    secret_fk_fields = ["api_key_secret"]
    api_key = MaskedSecretField(source="api_key_secret")
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
        fields = "__all__"
        read_only_fields = ["org", "created_by"]
