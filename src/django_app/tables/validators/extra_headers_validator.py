from typing import Any

from rest_framework import serializers


def validate_extra_headers(value: Any) -> None:
    """Require a flat `{header name: header value}` mapping of strings.

    The dict is sent as-is as HTTP headers by litellm and httpx, which reject a
    non-string value or an empty name only at request time, deep inside a run.
    """
    if not isinstance(value, dict):
        raise serializers.ValidationError("Must be an object of header names to values.")
    for name, header_value in value.items():
        if not name.strip():
            raise serializers.ValidationError("Header names must be non-empty strings.")
        if not isinstance(header_value, str):
            raise serializers.ValidationError(f"Header '{name}' must have a string value.")
