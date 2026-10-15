from rest_framework import serializers


class ExecutionTimeoutLimitsSerializer(serializers.Serializer):
    min_seconds = serializers.IntegerField(read_only=True)
    default_seconds = serializers.IntegerField(
        read_only=True, help_text="Execution timeout a new python code gets."
    )
    max_seconds = serializers.IntegerField(
        read_only=True,
        allow_null=True,
        help_text="Largest execution timeout; a higher value is saved as this. Null: no limit.",
    )
