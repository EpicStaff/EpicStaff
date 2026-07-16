from rest_framework import serializers

from tables.models.realtime_models import (
    RealtimeAgent,
    RealtimeAgentChat,
    RealtimeAgentDefinition,
    RealtimeSessionItem,
)


class RealtimeAgentSerializer(serializers.ModelSerializer):
    class Meta:
        model = RealtimeAgent
        exclude = ["agent"]


class RealtimeAgentDefinitionSerializer(serializers.ModelSerializer):
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
