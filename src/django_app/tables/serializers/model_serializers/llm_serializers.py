from rest_framework import serializers

from tables.serializers.model_serializers.tag_serializers import (
    LLMConfigTagSerializer,
    LLMModelTagSerializer,
)
from tables.models.llm_models import (
    DefaultLLMConfig,
    LLMConfig,
    LLMModel,
    RealtimeModel,
    RealtimeConfig,
    RealtimeTranscriptionModel,
    RealtimeTranscriptionConfig,
)
from tables.models.tag_models import LLMConfigTag, LLMModelTag
from tables.serializers.org_scoped_fields import OrgVisiblePrimaryKeyRelatedField


from ..utils.mixins import TagHandlingMixin


class DefaultLLMConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = DefaultLLMConfig
        fields = "__all__"


class RealtimeModelSerializer(serializers.ModelSerializer):
    class Meta:
        model = RealtimeModel
        fields = "__all__"
        read_only_fields = ["org", "created_by"]


class RealtimeConfigSerializer(serializers.ModelSerializer):
    provider_name = serializers.CharField(
        source="realtime_model.provider.name", read_only=True
    )
    # Org isolation (hybrid): built-in models OR the caller's active-org custom ones.
    realtime_model = OrgVisiblePrimaryKeyRelatedField(
        queryset=RealtimeModel.objects.all()
    )

    class Meta:
        model = RealtimeConfig
        fields = "__all__"
        read_only_fields = ["org", "created_by"]


class RealtimeTranscriptionModelSerializer(serializers.ModelSerializer):
    class Meta:
        model = RealtimeTranscriptionModel
        fields = "__all__"
        read_only_fields = ["org", "created_by"]


class RealtimeTranscriptionConfigSerializer(serializers.ModelSerializer):
    # Org isolation (hybrid): built-in models OR the caller's active-org custom ones.
    realtime_transcription_model = OrgVisiblePrimaryKeyRelatedField(
        queryset=RealtimeTranscriptionModel.objects.all()
    )

    class Meta:
        model = RealtimeTranscriptionConfig
        fields = "__all__"
        read_only_fields = ["org", "created_by"]


class LLMConfigSerializer(TagHandlingMixin, serializers.ModelSerializer):
    tags = LLMConfigTagSerializer(many=True, required=False)
    tag_model = LLMConfigTag
    # Org isolation (hybrid): built-in models OR the caller's active-org custom ones.
    model = OrgVisiblePrimaryKeyRelatedField(
        queryset=LLMModel.objects.all(), required=False, allow_null=True
    )

    class Meta:
        model = LLMConfig
        fields = "__all__"
        read_only_fields = ["org", "created_by"]


class LLMModelSerializer(TagHandlingMixin, serializers.ModelSerializer):
    capabilities = LLMModelTagSerializer(source="tags", many=True, required=False)
    tag_model = LLMModelTag

    class Meta:
        model = LLMModel
        fields = "__all__"
        read_only_fields = ["org", "created_by"]
