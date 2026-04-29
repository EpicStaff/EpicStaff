from dataclasses import dataclass
from typing import Optional


from rest_framework_simplejwt.tokens import RefreshToken

from tables.models.rbac_models import OrganizationUser


@dataclass
class TokenPair:
    access: str
    refresh: str

    @classmethod
    def for_user(cls, user) -> "TokenPair":
        refresh = RefreshToken.for_user(user)
        return cls(access=str(refresh.access_token), refresh=str(refresh))


class AuthService:
    """Read-side helpers for the auth surface (/me, introspect, reset)."""

    def get_memberships(self, user) -> list[OrganizationUser]:
        return list(user.organization_memberships.select_related("org", "role").all())

    def build_me_payload(self, user, request=None) -> dict:
        avatar_url: Optional[str] = None
        if getattr(user, "avatar", None):
            try:
                avatar_url = (
                    request.build_absolute_uri(user.avatar.url)
                    if request is not None
                    else user.avatar.url
                )
            except ValueError:
                # Avatar field may be set but file missing.
                avatar_url = None

        memberships = [
            {
                "organization": {"id": m.org_id, "name": m.org.name},
                "role": {"id": m.role_id, "name": m.role.name},
                "joined_at": m.joined_at,
            }
            for m in self.get_memberships(user)
        ]

        return {
            "id": user.id,
            "email": user.email,
            "display_name": user.display_name,
            "avatar_url": avatar_url,
            "is_superadmin": user.is_superadmin,
            "memberships": memberships,
        }
