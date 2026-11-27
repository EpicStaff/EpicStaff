"""The sections of a user's personal preferences: one serializer per section.

A section serializer is the single definition of its keys, their types, ranges and
defaults. `User.preferences` stores only the keys a user set; everything else reads as
the field's default.

Adding a section: write a `PreferenceSectionSerializer` subclass whose every field has a
`default`, then register it in `PREFERENCE_SECTIONS` under the name the URL and the
profile response use. `PATCH /api/profile/preferences/<name>/` and the `preferences`
of `GET /api/profile/` pick it up from there. Adding a key to a section needs no
migration. A field that holds the id of an organization's object is an
`OrgKeyedIdField`.
"""

from collections.abc import Mapping
from functools import cache
from zoneinfo import available_timezones

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from rbac.models.org_scoped import OrgScopedModel
from rbac.scoping.fields import org_visible_queryset

# Zone names the IANA database kept only as aliases, mapped to the current name.
_RENAMED_TIMEZONES = {"Europe/Kiev": "Europe/Kyiv"}

EDGE_STYLE_ORTHOGONAL = "orthogonal"
EDGE_STYLE_ADAPTIVE_CURVE = "adaptive-curve"
EDGE_STYLES = (EDGE_STYLE_ORTHOGONAL, EDGE_STYLE_ADAPTIVE_CURVE)

ON_OPEN_FIT = "fit"
ON_OPEN_RESTORE = "restore"
ON_OPEN_CHOICES = (ON_OPEN_FIT, ON_OPEN_RESTORE)


@cache
def _known_timezones() -> frozenset[str]:
    return frozenset(available_timezones())


class TimezoneField(serializers.CharField):
    """An IANA zone name, or null for "follow the browser"."""

    default_error_messages = {
        "unknown_timezone": 'Unknown timezone "{value}". Use an IANA name such as Europe/Kyiv.',
    }

    def __init__(self, **kwargs):
        kwargs.setdefault("allow_null", True)
        kwargs.setdefault("default", None)
        super().__init__(**kwargs)

    def to_internal_value(self, data):
        value = super().to_internal_value(data)
        value = _RENAMED_TIMEZONES.get(value, value)
        if value not in _known_timezones():
            self.fail("unknown_timezone", value=value)
        return value


@extend_schema_field(
    {
        "type": "object",
        "additionalProperties": {"type": "integer"},
        "description": "The chosen object's id in each organization, keyed by organization id.",
    }
)
class OrgKeyedIdField(serializers.Field):
    """The id of an organization's object, kept per organization: `{"<org_id>": <id>}`.

    Preferences follow the user across organizations, so a bare id would be read in an
    organization it does not belong to. A write changes only the active organization's
    entry: the client's entries for other organizations are ignored and the stored ones
    are kept. A missing or null entry for the active organization removes it.

    Reads from the serializer context a resolver of the active organization
    (`resolve_organization_id`) and the section as stored (`stored_section`). The resolver
    is called only here, so a request whose body has no organization-keyed field never
    checks the organization it names. It returns the organization id once the caller's
    membership is checked, or None when the request names no organization, and raises the
    membership error when the caller may not act in the organization it names.
    """

    default_error_messages = {
        "not_a_dict": 'Expected an object of ids keyed by organization id, got "{input_type}".',
        "incorrect_type": "Incorrect type. Expected an integer id, received {data_type}.",
        "does_not_exist": 'Invalid pk "{pk_value}" - object does not exist.',
        "organization_required": "Choosing this needs an active organization.",
    }

    def __init__(self, model: type[OrgScopedModel], **kwargs):
        kwargs.setdefault("default", dict)
        self.model = model
        super().__init__(**kwargs)

    def to_representation(self, value):
        return dict(value)

    def to_internal_value(self, data):
        if not isinstance(data, Mapping):
            self.fail("not_a_dict", input_type=type(data).__name__)
        organization_id = self.context["resolve_organization_id"]()
        if organization_id is None:
            self.fail("organization_required")
        organization_key = str(organization_id)
        stored = self.context.get("stored_section", {}).get(self.field_name, {})
        value = {key: object_id for key, object_id in stored.items() if key != organization_key}
        object_id = data.get(organization_key)
        if object_id is None:
            return value
        if isinstance(object_id, bool) or not isinstance(object_id, int):
            self.fail("incorrect_type", data_type=type(object_id).__name__)
        if not org_visible_queryset(self.model, organization_id).filter(pk=object_id).exists():
            self.fail("does_not_exist", pk_value=object_id)
        return {**value, organization_key: object_id}


class PreferenceSectionSerializer(serializers.Serializer):
    """A section of preferences. Rejects keys it does not define instead of dropping them."""

    default_error_messages = {"unknown_key": "Unknown preference."}

    def to_internal_value(self, data):
        if isinstance(data, Mapping):
            unknown_keys = sorted(str(key) for key in data if key not in self.fields)
            if unknown_keys:
                raise serializers.ValidationError(
                    {key: [self.error_messages["unknown_key"]] for key in unknown_keys}
                )
        return super().to_internal_value(data)


class GeneralPreferencesSerializer(PreferenceSectionSerializer):
    display_timezone = TimezoneField(
        help_text="Zone every date is shown in. null follows the browser's zone."
    )
    default_timezone = TimezoneField(
        help_text="Zone a new schedule trigger opens with. null follows the browser's zone."
    )


class FlowEditorPreferencesSerializer(PreferenceSectionSerializer):
    arrow_colors = serializers.BooleanField(default=True)
    show_inputs_outputs = serializers.BooleanField(default=False)
    edge_style = serializers.ChoiceField(choices=EDGE_STYLES, default=EDGE_STYLE_ORTHOGONAL)
    always_show_node_numbers = serializers.BooleanField(default=False)
    highlight_unused_nodes = serializers.BooleanField(default=False)
    show_minimap = serializers.BooleanField(default=True)
    on_open = serializers.ChoiceField(
        choices=ON_OPEN_CHOICES,
        default=ON_OPEN_FIT,
        help_text="fit shows the whole flow; restore returns to the last viewport.",
    )


PREFERENCE_SECTIONS: dict[str, type[PreferenceSectionSerializer]] = {
    "general": GeneralPreferencesSerializer,
    "flow_editor": FlowEditorPreferencesSerializer,
}
