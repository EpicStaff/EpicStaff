from rest_framework import serializers
from tables.models.user import DISPLAY_NAME_MAX_LENGTH, User

from rbac.profile.avatar import build_avatar_url


class OrganizationNestedSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(read_only=True)
    is_active = serializers.BooleanField(read_only=True)


class RoleNestedSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(read_only=True)


class MembershipNestedSerializer(serializers.Serializer):
    """Nested under UserResponseSerializer (cross-org list)."""

    id = serializers.IntegerField(read_only=True)
    organization = OrganizationNestedSerializer(source="org", read_only=True)
    role = RoleNestedSerializer(read_only=True)
    joined_at = serializers.DateTimeField(read_only=True)


class UserResponseSerializer(serializers.ModelSerializer):
    """Cross-org user payload. Used by /api/admin/users/* endpoints."""

    memberships = MembershipNestedSerializer(
        source="organization_memberships", many=True, read_only=True
    )
    avatar_url = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "display_name",
            "avatar",
            "avatar_url",
            "is_superadmin",
            "is_active",
            "created_at",
            "updated_at",
            "memberships",
        ]
        read_only_fields = fields

    def get_avatar_url(self, user):
        return build_avatar_url(user, self.context.get("request"))


# ---- request serializers (schema-only; real validation in
#      UserValidationService) ----


class UserCreateRequestSerializer(serializers.Serializer):
    """`POST /api/admin/users/` — schema for drf-spectacular."""

    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)
    display_name = serializers.CharField(
        required=False,
        allow_null=True,
        max_length=DISPLAY_NAME_MAX_LENGTH,
        help_text="Trimmed. Omit or send null to derive it from the email.",
    )
    organization_id = serializers.IntegerField(required=False)
    role_id = serializers.IntegerField(required=False)
