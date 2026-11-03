"""Whose FILES permissions a run's temporary storage account is built from."""

from dataclasses import dataclass, replace

from loguru import logger
from rbac.access.principals import acting_person
from rbac.access.resolver import PermissionResolver
from rbac.exceptions import OrgMembershipRequiredError
from rbac.identity.api_keys.principals import PrincipalResolver
from rbac.models import ApiKey
from src.shared.models.storage_scope import StorageAction
from tables.models import Session
from tables.models.session_models import SessionPrincipal
from tables.models.user import User

from storage_credentials.storage_actions import storage_actions_for


@dataclass(frozen=True)
class ActingIdentity:
    """Who a run acts as, for the files attached to it.

    Three states: attributed (`principal` set), unattributed (a schedule, webhook or
    telegram run with no user and no API key) and denied (an identity that existed
    but can no longer be resolved).

    Attributes:
        principal: What `PermissionResolver` resolves: a `User`, the system API key's
            principal, or a pinned-org principal such as a plugin service account.
            For a run started with a USER API key it is the key's owner, whose live
            permissions in the key's organization the key carries.
        api_key: The API key the run was started with, if any.
        denied: No permissions at all, whatever the other fields say.
        bounded_by: For a sub-flow, the identity that started the root session. The
            sub-flow may do only what both it and that identity may do.
    """

    principal: object | None = None
    api_key: ApiKey | None = None
    denied: bool = False
    bounded_by: "ActingIdentity | None" = None

    @classmethod
    def unattributed(cls) -> "ActingIdentity":
        return cls()

    @classmethod
    def denied_everything(cls) -> "ActingIdentity":
        return cls(denied=True)

    @classmethod
    def for_request(cls, user: object | None, api_key: ApiKey | None) -> "ActingIdentity":
        """The identity of a request: `request.user` and the API key in `request.auth`."""
        if user is None:
            return cls.unattributed()
        return cls(principal=user, api_key=api_key)

    @classmethod
    def for_sub_flow(
        cls, user: object | None, api_key: ApiKey | None, parent_session_id: int
    ) -> "ActingIdentity":
        """The identity of a request that starts a sub-flow of `parent_session_id`.

        The request's own identity (normally the sub-flow tool's API key) is bounded by
        whoever started the root session. Neither alone decides: the tool's key says
        nothing about who chose to run the chain, and a caller naming another user's
        session as parent must not gain that user's permissions.
        """
        return replace(
            cls.for_request(user, api_key), bounded_by=cls.of_root_session(parent_session_id)
        )

    @classmethod
    def of_root_session(cls, parent_session_id: int) -> "ActingIdentity":
        """The identity of the run that started the chain `parent_session_id` belongs to."""
        root_session_id = _root_session_id(parent_session_id)
        principal_row = (
            SessionPrincipal.objects.select_related("user", "api_key")
            .filter(session_id=root_session_id)
            .first()
        )
        if principal_row is None:
            return cls.denied_everything()
        kind = SessionPrincipal.ActionKind
        if principal_row.kind == kind.TRIGGER:
            return cls.unattributed()
        if principal_row.kind == kind.USER and principal_row.user is not None:
            return cls(principal=principal_row.user)
        if principal_row.kind == kind.API_KEY_SYSTEM and principal_row.api_key is not None:
            return cls(
                principal=PrincipalResolver().resolve(principal_row.api_key),
                api_key=principal_row.api_key,
            )
        api_key = principal_row.api_key
        if (
            principal_row.kind == kind.API_KEY_USER
            and principal_row.user is not None
            and api_key is not None
            and not api_key.is_revoked
            and not api_key.is_expired
        ):
            return cls(principal=principal_row.user, api_key=api_key)
        # A plugin's permissions come from its package, which a stored row cannot
        # rebuild; a deleted, revoked or expired key has no access left to inherit.
        return cls.denied_everything()

    @property
    def recorded_user(self) -> User | None:
        """The user to record on the account: set only when no API key is involved.

        For a plugin it is the person the run is made on behalf of, if any: the
        plugin's own access has no user to revoke by, but that person's does.
        """
        if self.api_key is None:
            return acting_person(self.principal)
        return None

    def shared_actions(self, org_id: int) -> frozenset[StorageAction]:
        """What this identity may do to the shared files of organization `org_id`."""
        actions = self._own_actions(org_id)
        if self.bounded_by is not None:
            actions &= self.bounded_by.shared_actions(org_id)
        return actions

    def _own_actions(self, org_id: int) -> frozenset[StorageAction]:
        if self.denied:
            return frozenset()
        if self.principal is None:
            logger.info(
                "Run has no acting identity; granting every storage action on shared folders"
            )
            return frozenset(StorageAction)
        if getattr(self.principal, "is_active", True) is False:
            return frozenset()
        try:
            effective = PermissionResolver().resolve(user=self.principal, org_id=org_id)
        except OrgMembershipRequiredError:
            return frozenset()
        return storage_actions_for(effective)


def _root_session_id(session_id: int) -> int:
    """Follow `parent_session` up to the session that is not a sub-flow."""
    visited: set[int] = set()
    while session_id not in visited:
        visited.add(session_id)
        parent_id = (
            Session.objects.filter(pk=session_id)
            .values_list("parent_session_id", flat=True)
            .first()
        )
        if parent_id is None:
            return session_id
        session_id = parent_id
    return session_id
