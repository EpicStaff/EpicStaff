from rest_framework import serializers


class MembershipResponseSerializer(serializers.Serializer):
    """Cross-org membership row (one per user-in-org). Presentation only —
    the org, user, and role are read off the OrganizationUser instance;
    all business logic lives in MembershipManagementService.
    """

    def to_representation(self, instance):
        user = instance.user
        return {
            "id": instance.id,
            "org": {"id": instance.org_id, "name": instance.org.name},
            "user": {
                "id": user.id,
                "email": user.email,
                "display_name": user.display_name,
                "avatar_url": self._avatar_url(user),
                "is_active": user.is_active,
            },
            "role": {"id": instance.role_id, "name": instance.role.name},
            "joined_at": instance.joined_at,
        }

    def _avatar_url(self, user):
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


class MembershipCreateRequestSerializer(serializers.Serializer):
    """`POST /api/admin/memberships/` — link an EXISTING user to an org.

    Exactly one of `email` / `user_id` identifies the account; account
    creation stays a superadmin-only operation on /api/admin/users/."""

    org_id = serializers.IntegerField()
    email = serializers.EmailField(required=False)
    user_id = serializers.IntegerField(required=False)
    role_id = serializers.IntegerField()


class MembershipRoleUpdateRequestSerializer(serializers.Serializer):
    """`PATCH /api/admin/memberships/{id}/`."""

    role_id = serializers.IntegerField()
