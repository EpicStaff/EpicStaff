from rest_framework import serializers


class LLMConfigTimeoutLimitsSerializer(serializers.Serializer):
    min_seconds = serializers.IntegerField(read_only=True)
    max_seconds = serializers.IntegerField(
        read_only=True, help_text="Largest timeout an LLM config may be saved with."
    )
