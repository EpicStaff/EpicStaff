from drf_spectacular.utils import extend_schema_field
from rbac.profile.preferences.sections import FlowEditorPreferencesSerializer, TimezoneField
from rest_framework import serializers
from rest_framework.fields import empty


class FlowViewOverrideSerializer(FlowEditorPreferencesSerializer):
    """The keys a user's personal override for one flow may hold.

    The flow_editor section's keys plus `default_timezone`, which overrides the account's
    `general.default_timezone` for this flow only. Kept apart from the flow_editor section
    so the account's section does not gain a timezone. Validate it with `partial=True`:
    a key left out follows the account preference, so no default may be filled in.
    """

    default_timezone = TimezoneField(
        allow_null=False,
        required=False,
        default=empty,
        help_text=(
            "Zone a new schedule trigger in this flow opens with, as an IANA name. Leave "
            "the key out to follow the account's general.default_timezone; null is rejected."
        ),
    )


@extend_schema_field(FlowViewOverrideSerializer)
class _FlowViewOverrideField(serializers.DictField):
    """A plain dict at runtime; documented with the override's keys in the schema.

    The output keeps only the keys `FlowViewOverrideSerializer` defines. A row saved
    before a key was removed or renamed still holds the old key; shown back, the client
    would send it with its next PUT and every save would fail with 400. Only keys are
    filtered: a stored value of a known key that is no longer a valid choice is shown as is.
    """

    def to_representation(self, value):
        known_keys = FlowViewOverrideSerializer().fields
        return super().to_representation(
            {key: setting for key, setting in value.items() if key in known_keys}
        )


class GraphViewSettingsSerializer(serializers.Serializer):
    settings = _FlowViewOverrideField(
        help_text=(
            "The keys this flow overrides for the caller: the flow_editor preference keys "
            "and default_timezone. The keys left out follow the caller's account preferences."
        )
    )

    def validate_settings(self, value: dict) -> dict:
        overrides = FlowViewOverrideSerializer(data=value, partial=True)
        overrides.is_valid(raise_exception=True)
        return dict(overrides.validated_data)
