from rest_framework import serializers

from tables.models import (
    DefaultModels,
)
from tables.models.realtime_models import DefaultRealtimeAgentConfig


class DefaultModelsSerializer(serializers.ModelSerializer):
    class Meta:
        model = DefaultModels
        fields = "__all__"
