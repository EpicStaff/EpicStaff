from rest_framework import serializers

from agents.models.agent_models import AgentDefinition
from tables.models.llm_models import RealtimeConfig, RealtimeTranscriptionConfig
from tables.models.realtime_models import (
    RealtimeAgentChat,
    RealtimeAgentDefinition,
    RealtimeSessionItem,
)
from tables.serializers.org_scoped_fields import (
    OrganizationScopedPrimaryKeyRelatedField,
    OrgScopedPrimaryKeyRelatedField,
)


class RealtimeAgentDefinitionSerializer(serializers.ModelSerializer):
    # Org isolation: only configs/agent definitions from the caller's active
    # org may be referenced.
    agent_definition = OrganizationScopedPrimaryKeyRelatedField(
        queryset=AgentDefinition.objects.all()
    )
    realtime_config = OrgScopedPrimaryKeyRelatedField(
        queryset=RealtimeConfig.objects.all(), required=False, allow_null=True
    )
    realtime_transcription_config = OrgScopedPrimaryKeyRelatedField(
        queryset=RealtimeTranscriptionConfig.objects.all(),
        required=False,
        allow_null=True,
    )

    class Meta:
        model = RealtimeAgentDefinition
        fields = "__all__"


class RealtimeSessionItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = RealtimeSessionItem
        fields = "__all__"


class RealtimeAgentChatSerializer(serializers.ModelSerializer):
    class Meta:
        model = RealtimeAgentChat
        fields = "__all__"
