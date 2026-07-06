from rest_framework import serializers

from tables.models import (
    DefaultModels,
)


class DefaultModelsSerializer(serializers.ModelSerializer):
    class Meta:
        model = DefaultModels
        fields = "__all__"
