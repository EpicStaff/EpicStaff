import abc
from dataclasses import dataclass

# EpicStaff's own limit for a user's display name, and the operator_profile column's.
OPERATOR_NAME_MAX_LENGTH = 255


@dataclass(frozen=True)
class IntrospectedUser:
    user_id: int
    org_ids: list[int]
    is_superadmin: bool
    # None when EpicStaff sent no name: releases before introspection carried one.
    display_name: str | None = None


ALL_CHATS_ACTIONS = frozenset({"create", "read", "update", "delete", "use"})


class AbstractIdentityProvider(abc.ABC):
    @abc.abstractmethod
    async def introspect(self, jwt: str) -> IntrospectedUser | None:
        """None when the token is invalid, expired, revoked or the user inactive."""

    @abc.abstractmethod
    async def chats_actions(self, jwt: str, org_id: int) -> set[str]:
        """The `chats` actions the user holds in the org. Raises NotMemberError."""
