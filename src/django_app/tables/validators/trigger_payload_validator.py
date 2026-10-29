import json
import re
from typing import Any

from rest_framework import serializers

from tables.constants.trigger_payload_constants import MAX_TRIGGER_PAYLOAD_BYTES

# A `\u0000` escape preceded by an even number of backslashes. An odd number means the
# backslash before `u0000` is itself escaped, i.e. the literal text `\u0000`, which is fine.
_ESCAPED_NUL = re.compile(r"(?<!\\)(?:\\\\)*\\u0000")


def validate_trigger_payload(value: Any) -> dict:
    """Reject a trigger payload Postgres `jsonb` cannot store or that exceeds the size cap.

    The size is the UTF-8 byte length of the compact JSON encoding with non-ASCII
    characters kept as-is, so formatting whitespace does not count and a Cyrillic or
    emoji character costs its real 2-4 bytes rather than a 6-12 byte `\\uXXXX` escape.

    Raises:
        serializers.ValidationError: The value is not a JSON object, contains a NUL
            character or an unpaired surrogate (both rejected by `jsonb`), or exceeds
            `MAX_TRIGGER_PAYLOAD_BYTES`.
    """
    if not isinstance(value, dict):
        raise serializers.ValidationError("Test payload must be a JSON object.")
    encoded = json.dumps(value, separators=(",", ":"), ensure_ascii=False)
    if _ESCAPED_NUL.search(encoded):
        raise serializers.ValidationError(
            "Test payload must not contain the NUL character (\\u0000) in any key or value."
        )
    try:
        encoded_size = len(encoded.encode("utf-8"))
    except UnicodeEncodeError:
        raise serializers.ValidationError(
            "Test payload must not contain unpaired Unicode surrogates."
        ) from None
    if encoded_size > MAX_TRIGGER_PAYLOAD_BYTES:
        raise serializers.ValidationError(
            f"Test payload must not exceed {MAX_TRIGGER_PAYLOAD_BYTES} bytes "
            f"of compact JSON (got {encoded_size})."
        )
    return value
