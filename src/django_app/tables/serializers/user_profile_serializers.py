from rest_framework import serializers

from tables.serializers.user_management_serializers import UserResponseSerializer


class ProfileResponseSerializer(UserResponseSerializer):
    """GET / PATCH / POST-avatar response for /api/profile/.

    Strict superset of UserResponseSerializer:
    same fields, plus `avatar_url`, `active_organization_id`,
    `active_permissions`. Memberships are filtered to active
    organizations at the queryset layer (UserProfileService.get_profile),
    so this serializer stays shape-stable.
    """

    avatar_url = serializers.SerializerMethodField()
    active_organization_id = serializers.IntegerField(
        source="_active_organization_id", allow_null=True, default=None, read_only=True
    )
    active_permissions = serializers.JSONField(
        source="_active_permissions", allow_null=True, default=None, read_only=True
    )

    class Meta(UserResponseSerializer.Meta):
        fields = UserResponseSerializer.Meta.fields + [
            "avatar_url",
            "active_organization_id",
            "active_permissions",
        ]
        read_only_fields = fields

    def get_avatar_url(self, user):
        if not user.avatar:
            return None
        request = self.context.get("request")
        try:
            return (
                request.build_absolute_uri(user.avatar.url)
                if request is not None
                else user.avatar.url
            )
        except ValueError:
            return None


# ---- request serializers (schema-only; validation in UserValidationService) ----


class ProfilePatchRequestSerializer(serializers.Serializer):
    """`PATCH /api/profile/` — schema for drf-spectacular only."""

    display_name = serializers.CharField(required=False, allow_null=True)


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
    refresh = serializers.CharField()
