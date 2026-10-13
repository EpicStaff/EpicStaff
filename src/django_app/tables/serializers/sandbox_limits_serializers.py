from rest_framework import serializers


class SandboxLimitsSerializer(serializers.Serializer):
    max_execution_timeout_minutes = serializers.IntegerField(
        read_only=True,
        help_text=(
            "Largest execution timeout a node may be given, in minutes: the sandbox "
            "SANDBOX_EXECUTION_TIMEOUT rounded down to whole minutes."
        ),
    )
