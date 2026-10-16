from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from rbac.serializers.users import (
    MembershipNestedSerializer,
    UserResponseSerializer,
)


class ShortcutCustomEntrySerializer(serializers.Serializer):
    action = serializers.CharField()
    keys = serializers.CharField()


class ShortcutOverridesSerializer(serializers.Serializer):
    overrides = serializers.DictField(child=serializers.CharField())
    custom = ShortcutCustomEntrySerializer(many=True)


class ProfileResponseSerializer(UserResponseSerializer):
    """GET / PATCH / POST-avatar response for /api/profile/.

    Strict superset of UserResponseSerializer: same fields, plus
    `avatar_url`, `active_organization_id`, `active_permissions` and
    `shortcut_overrides` (the user's own preference, so it stays off the
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
    shortcut_overrides = serializers.SerializerMethodField()

    class Meta(UserResponseSerializer.Meta):
        fields = [
            *UserResponseSerializer.Meta.fields,
            "avatar_url",
            "active_organization_id",
            "active_permissions",
            "shortcut_overrides",
        ]
        read_only_fields = fields

    @extend_schema_field(ShortcutOverridesSerializer)
    def get_shortcut_overrides(self, user):
        return user.shortcut_overrides


# ---- request serializers (schema-only; validation in UserValidationService) ----


class ProfilePatchRequestSerializer(serializers.Serializer):
    """`PATCH /api/profile/` — schema for drf-spectacular only."""

    display_name = serializers.CharField(required=False, allow_null=True)
    shortcut_overrides = ShortcutOverridesSerializer(
        required=False,
        help_text="Replaces the whole value: overrides and custom shortcuts.",
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
