from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from tables.models.user import (
    SHORTCUTS_MAX_PARAM_INTEGER,
    SHORTCUTS_MAX_PARAMS,
    SHORTCUTS_MAX_TEXT_LENGTH,
)

from rbac.serializers.users import (
    MembershipNestedSerializer,
    UserResponseSerializer,
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


class ProfileResponseSerializer(UserResponseSerializer):
    """GET / PATCH / POST-avatar response for /api/profile/.

    Strict superset of UserResponseSerializer: same fields, plus
    `avatar_url`, `active_organization_id`, `active_permissions` and
    `custom_shortcuts` (the user's own preference, so it stays off the
    admin user directory's UserResponseSerializer). The
    `memberships` list is computed in UserProfileService.get_profile — a
    normal user's real active memberships, or (for a superadmin) every active
    organization with the built-in Superadmin role — so the response shape is
    unchanged.
    """

    avatar_url = serializers.SerializerMethodField()
    memberships = MembershipNestedSerializer(
        source="_profile_memberships", many=True, read_only=True
    )
    active_organization_id = serializers.IntegerField(
        source="_active_organization_id", allow_null=True, default=None, read_only=True
    )
    active_permissions = serializers.JSONField(
        source="_active_permissions", allow_null=True, default=None, read_only=True
    )
    custom_shortcuts = serializers.SerializerMethodField()

    class Meta(UserResponseSerializer.Meta):
        fields = [
            *UserResponseSerializer.Meta.fields,
            "avatar_url",
            "active_organization_id",
            "active_permissions",
            "custom_shortcuts",
        ]
        read_only_fields = fields

    @extend_schema_field(CustomShortcutsSerializer)
    def get_custom_shortcuts(self, user):
        return user.custom_shortcuts


# ---- request serializers (schema-only; validation in UserValidationService) ----


class ProfilePatchRequestSerializer(serializers.Serializer):
    """`PATCH /api/profile/` — schema for drf-spectacular only."""

    display_name = serializers.CharField(required=False, allow_null=True)
    custom_shortcuts = CustomShortcutsSerializer(
        required=False,
        help_text="Replaces the whole value: the custom shortcuts and the key overrides.",
    )


class PasswordChangeRequestRequestSerializer(serializers.Serializer):
    """`POST /api/profile/password-change/request/` — schema only."""

    current_password = serializers.CharField(write_only=True)


class PasswordChangeRequestResponseSerializer(serializers.Serializer):
    """`POST /api/profile/password-change/request/` — response schema."""

    ticket = serializers.CharField()
    expires_in = serializers.IntegerField()


class PasswordChangeConfirmRequestSerializer(serializers.Serializer):
    """`POST /api/profile/password-change/confirm/` — schema only."""

    ticket = serializers.CharField()
    new_password = serializers.CharField(write_only=True)


class PasswordChangeConfirmResponseSerializer(serializers.Serializer):
    """`POST /api/profile/password-change/confirm/` — response schema."""

    access = serializers.CharField()
