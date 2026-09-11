from rest_framework import serializers

from tables.models.rbac_models import User


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


# ---- request serializers (schema-only; real validation in
#      UserValidationService) ----


class UserCreateRequestSerializer(serializers.Serializer):
    """`POST /api/admin/users/` — schema for drf-spectacular."""

    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)
    organization_id = serializers.IntegerField(required=False)
    role_id = serializers.IntegerField(required=False)
