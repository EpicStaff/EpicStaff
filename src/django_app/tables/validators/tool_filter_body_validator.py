from tables.validators.filter_body_shape import validate_filter_body_shape

_ALLOWED_KEY_TYPES: dict[str, type | tuple[type, ...]] = {
    "showFavoriteOnly": bool,
    "showNotFavoriteOnly": bool,
    "sourceBuiltIn": bool,
    "sourceCustom": bool,
    "usageBuckets": list,
    "unusedOnly": bool,
    "sortOrder": str,
    "includedToolIds": (list, type(None)),
    "includedLabelIds": (list, type(None)),
    "customConditions": (list, type(None)),
}


def validate_tool_filter_body_shape(value):
    """Validate the structural shape of a tool filter preset body."""
    return validate_filter_body_shape(value, _ALLOWED_KEY_TYPES)
