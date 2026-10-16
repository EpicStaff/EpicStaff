from django.conf import settings
from rest_framework import serializers


def normalize_execution_timeout(seconds: int) -> int:
    """Return the execution timeout to store for a PythonCode.

    Below the minimum is rejected. Above the maximum is saved as the maximum rather than
    rejected: the maximum is deployment configuration that can be lowered after a flow was
    saved or exported, and such a flow must still save and import. With no maximum the
    value is kept; one too large for the column is already rejected by the field itself.

    Raises:
        serializers.ValidationError: The timeout is below the minimum.
    """
    if seconds < settings.MIN_EXECUTION_TIMEOUT_SECONDS:
        raise serializers.ValidationError(
            f"Execution timeout must be at least {settings.MIN_EXECUTION_TIMEOUT_SECONDS} seconds."
        )
    if settings.MAX_EXECUTION_TIMEOUT_SECONDS is None:
        return seconds
    return min(seconds, settings.MAX_EXECUTION_TIMEOUT_SECONDS)
