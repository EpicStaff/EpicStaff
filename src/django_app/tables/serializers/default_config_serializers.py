from rbac.scoping.fields import OrgScopedPrimaryKeyRelatedField
from rest_framework import serializers
from tables.models import (
    DefaultModels,
    EmbeddingConfig,
    LLMConfig,
    RealtimeConfig,
    RealtimeTranscriptionConfig,
)


class DefaultModelsSerializer(serializers.ModelSerializer):
    agent_llm_config = OrgScopedPrimaryKeyRelatedField(
        queryset=LLMConfig.objects.all(), required=False, allow_null=True
    )
    agent_fcm_llm_config = OrgScopedPrimaryKeyRelatedField(
        queryset=LLMConfig.objects.all(), required=False, allow_null=True
    )
    voice_llm_config = OrgScopedPrimaryKeyRelatedField(
        queryset=RealtimeConfig.objects.all(), required=False, allow_null=True
    )
    transcription_llm_config = OrgScopedPrimaryKeyRelatedField(
        queryset=RealtimeTranscriptionConfig.objects.all(), required=False, allow_null=True
    )
    project_manager_llm_config = OrgScopedPrimaryKeyRelatedField(
        queryset=LLMConfig.objects.all(), required=False, allow_null=True
    )
    memory_embedding_config = OrgScopedPrimaryKeyRelatedField(
        queryset=EmbeddingConfig.objects.all(), required=False, allow_null=True
    )
    memory_llm_config = OrgScopedPrimaryKeyRelatedField(
        queryset=LLMConfig.objects.all(), required=False, allow_null=True
    )

    class Meta:
        model = DefaultModels
        exclude = ["org", "created_by"]
