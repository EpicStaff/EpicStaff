"""OpenAPI schemas for the user's custom keyboard shortcuts (`User.custom_shortcuts`).

These serializers only describe the value to drf-spectacular; UserValidationService
validates it.
"""

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from tables.models.user import (
    SHORTCUTS_MAX_PARAM_INTEGER,
    SHORTCUTS_MAX_PARAMS,
    SHORTCUTS_MAX_TEXT_LENGTH,
)


@extend_schema_field(
    {
        "oneOf": [
            {"type": "integer", "minimum": 0, "maximum": SHORTCUTS_MAX_PARAM_INTEGER},
            {"type": "string", "minLength": 1, "maxLength": SHORTCUTS_MAX_TEXT_LENGTH},
        ]
    }
)
class ShortcutParamValueField(serializers.JSONField):
    pass


class ShortcutCustomEntrySerializer(serializers.Serializer):
    action = serializers.CharField()
    keys = serializers.CharField(allow_null=True)
    params = serializers.DictField(
        child=ShortcutParamValueField(),
        required=False,
        help_text=(
            f"Optional arguments of the action, 1 to {SHORTCUTS_MAX_PARAMS} entries: "
            f"names are printable ASCII of 1 to {SHORTCUTS_MAX_TEXT_LENGTH} characters, values "
            "are such strings or non-negative integers. Omit it when the action takes none. "
            'Example: {"flowId": 12} for "node.subgraph".'
        ),
    )


class CustomShortcutsSerializer(serializers.Serializer):
    custom = ShortcutCustomEntrySerializer(many=True)
    overrides = serializers.DictField(
        child=serializers.CharField(allow_null=True),
        help_text=(
            "The user's own keys for built-in actions, by action id. "
            "null means the action deliberately has no key."
        ),
    )


# Returns the stored value unchanged: the app loads /api/profile/ on start, so a stored
# value that drifted from this schema must not fail the request.
@extend_schema_field(CustomShortcutsSerializer)
class CustomShortcutsField(serializers.JSONField):
    pass
