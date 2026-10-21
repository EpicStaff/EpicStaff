import re
from typing import Any

from rest_framework import serializers

# RFC 7230 `token`: the only characters an HTTP header name may contain.
_HEADER_NAME_PATTERN = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
# C0 controls (including CR and LF) and DEL; a horizontal tab is legal in a value.
_FORBIDDEN_VALUE_PATTERN = re.compile(r"[\x00-\x08\x0a-\x1f\x7f]")


def validate_extra_headers(value: Any) -> None:
    """Require a flat `{header name: header value}` mapping of valid HTTP headers.

    The dict is sent as-is as HTTP headers by litellm and httpx, which reject an
    invalid name, a non-string value or a value with control characters only at
    request time, deep inside a run. Names are compared case-insensitively, as HTTP
    does, so `X-A` and `x-a` count as one header.
    """
    if not isinstance(value, dict):
        raise serializers.ValidationError("Must be an object of header names to values.")
    seen_names: dict[str, str] = {}
    for name, header_value in value.items():
        if not isinstance(name, str) or not name.strip():
            raise serializers.ValidationError("Header names must be non-empty strings.")
        if not _HEADER_NAME_PATTERN.fullmatch(name):
            raise serializers.ValidationError(
                f"Header name '{name}' is not a valid HTTP header name."
            )
        lowered_name = name.lower()
        if lowered_name in seen_names:
            raise serializers.ValidationError(
                f"Header '{name}' duplicates '{seen_names[lowered_name]}': "
                "header names are case-insensitive."
            )
        seen_names[lowered_name] = name
        if not isinstance(header_value, str):
            raise serializers.ValidationError(f"Header '{name}' must have a string value.")
        if _FORBIDDEN_VALUE_PATTERN.search(header_value):
            raise serializers.ValidationError(
                f"Header '{name}' value must not contain control characters or line breaks."
            )
