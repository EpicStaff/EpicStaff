from rest_framework import serializers


def _avatar_url(user, request):
    """Absolute avatar URL, or None when unset or unresolvable."""
    if not user.avatar:
        return None
    try:
        return (
            request.build_absolute_uri(user.avatar.url)
            if request is not None
            else user.avatar.url
        )
    except ValueError:
        return None


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
                "avatar_url": _avatar_url(user, self.context.get("request")),
                "is_active": user.is_active,
            },
            "role": {"id": instance.role_id, "name": instance.role.name},
            "joined_at": instance.joined_at,
        }


class AssignableUserSerializer(serializers.Serializer):
    """A candidate for `POST /api/admin/memberships/`. Presentation only.

    `org_ids` reads the `_visible_memberships` prefetch attached by
    MembershipManagementService, already limited to the caller's readable orgs.
    """

    def to_representation(self, instance):
        return {
            "id": instance.id,
            "email": instance.email,
            "display_name": instance.display_name,
            "avatar_url": _avatar_url(instance, self.context.get("request")),
            "org_ids": [m.org_id for m in instance._visible_memberships],
        }


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
