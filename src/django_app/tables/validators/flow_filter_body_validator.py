from tables.validators.filter_body_shape import validate_filter_body_shape

_ALLOWED_KEY_TYPES: dict[str, type | tuple[type, ...]] = {
    "sortOrder": str,
    "includedFlowIds": (list, type(None)),
    "includedLabelIds": (list, type(None)),
    "customConditions": (list, type(None)),
}


def validate_flow_filter_body_shape(value):
    """Validate the structural shape of a flow filter preset body."""
    return validate_filter_body_shape(value, _ALLOWED_KEY_TYPES)
