from django.conf import settings
from rest_framework import serializers


def normalize_execution_timeout(seconds: int) -> int:
    """Return the execution timeout to store for a PythonCode written through the API.

    Below the minimum is rejected: the editor never sends one, so it is a broken request.
    Above the maximum is saved as the maximum rather than rejected: the maximum is
    deployment configuration that can be lowered after a flow was saved, and such a flow
    must still save. With no maximum the value is kept; one too large for the column is
    already rejected by the field itself.

    Raises:
        serializers.ValidationError: The timeout is below the minimum.
    """
    if seconds < settings.MIN_EXECUTION_TIMEOUT_SECONDS:
        raise serializers.ValidationError(
            f"Execution timeout must be at least {settings.MIN_EXECUTION_TIMEOUT_SECONDS} seconds."
        )
    return _at_most_maximum(seconds)


def normalize_imported_execution_timeout(seconds: int) -> int:
    """Return the execution timeout to store for a PythonCode from an import file.

    A file can come from another deployment or an older release with other limits, so a
    value outside this deployment's range is moved to the nearest limit instead of
    failing the whole import: below the minimum becomes the minimum, above the maximum
    becomes the maximum.
    """
    return _at_most_maximum(max(seconds, settings.MIN_EXECUTION_TIMEOUT_SECONDS))


def _at_most_maximum(seconds: int) -> int:
    if settings.MAX_EXECUTION_TIMEOUT_SECONDS is None:
        return seconds
    return min(seconds, settings.MAX_EXECUTION_TIMEOUT_SECONDS)
