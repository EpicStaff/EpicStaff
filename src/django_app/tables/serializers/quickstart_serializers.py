from rest_framework import serializers
from tables.models.provider import Provider


class QuickstartSerializer(serializers.Serializer):
    provider = serializers.CharField()
    api_key = serializers.CharField()

    def validate_provider(self, value):
        if not Provider.objects.filter(name=value).exists():
            raise serializers.ValidationError(f"Provider '{value}' does not exist.")
        return value
