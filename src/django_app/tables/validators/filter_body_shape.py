from rest_framework import serializers


def validate_filter_body_shape(value, allowed_key_types):
    """Validate the structural shape of a filter preset body.

    Rejects unknown keys and wrong top-level types. Does not deeply validate
    list item types or the condition grammar inside customConditions.

    Args:
        value: The raw deserialized JSON value from the request.
        allowed_key_types: Mapping of key name to expected Python type(s).
    """
    if not isinstance(value, dict):
        raise serializers.ValidationError(
            "filter_body must be a JSON object, not a bare value."
        )

    unknown_keys = set(value) - set(allowed_key_types)
    if unknown_keys:
        raise serializers.ValidationError(
            f"filter_body has unrecognized key(s): {', '.join(sorted(unknown_keys))}. "
            f"Allowed keys: {', '.join(sorted(allowed_key_types))}."
        )

    for key, expected_type in allowed_key_types.items():
        if key in value and not isinstance(value[key], expected_type):
            if isinstance(expected_type, tuple):
                type_names = " or ".join(
                    t.__name__ if t is not type(None) else "null" for t in expected_type
                )
            else:
                type_names = expected_type.__name__
            raise serializers.ValidationError(
                f"filter_body.{key} must be {type_names}, "
                f"got {type(value[key]).__name__}."
            )

    return value
