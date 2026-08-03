from rest_framework import serializers

from tables.serializers.model_serializers.embedding_serializers import (
    EmbeddingConfigSerializer,
)
from tables.serializers.model_serializers.llm_serializers import (
    LLMConfigSerializer,
    RealtimeConfigSerializer,
    RealtimeTranscriptionConfigSerializer,
)
from tables.models.provider import Provider
from tables.models.secret_models import Secret
from tables.serializers.org_scoped_fields import OrgScopedPrimaryKeyRelatedField


class QuickstartSerializer(serializers.Serializer):
    provider = serializers.CharField()
    # Exactly one credential form. `api_key` is the cold start (no secrets exist
    # yet); `api_key_secret_id` reuses one the caller already owns.
    api_key = serializers.CharField(required=False)
    api_key_secret_id = OrgScopedPrimaryKeyRelatedField(
        queryset=Secret.objects.all(), required=False
    )

    def validate_provider(self, value):
        if not Provider.objects.filter(name=value).exists():
            raise serializers.ValidationError(f"Provider '{value}' does not exist.")
        return value

    def validate(self, attrs):
        has_api_key = bool(attrs.get("api_key"))
        has_secret = attrs.get("api_key_secret_id") is not None

        if has_api_key and has_secret:
            raise serializers.ValidationError(
                "Provide either api_key or api_key_secret_id, not both."
            )
        if not has_api_key and not has_secret:
            raise serializers.ValidationError(
                "Provide either api_key or api_key_secret_id."
            )
        return attrs


class QuickstartConfigSerializer(serializers.Serializer):
    config_name = serializers.CharField()
    llm_config = LLMConfigSerializer(allow_null=True)
    embedding_config = EmbeddingConfigSerializer(allow_null=True)
    realtime_config = RealtimeConfigSerializer(allow_null=True)
    realtime_transcription_config = RealtimeTranscriptionConfigSerializer(
        allow_null=True
    )


class QuickstartStatusSerializer(serializers.Serializer):
    supported_providers = serializers.ListField(child=serializers.CharField())
    last_config = QuickstartConfigSerializer(allow_null=True)
    is_synced = serializers.BooleanField()
