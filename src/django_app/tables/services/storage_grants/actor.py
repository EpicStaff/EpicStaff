from collections.abc import Callable, Iterable

from rbac.access.effective import EffectivePermissions
from rbac.access.resolver import PermissionResolver, resolve_request_permissions
from rbac.exceptions import OrgMembershipRequiredError
from rbac.models.enums import Permission, ResourceType
from src.shared.models.storage_scope import StorageAction

# The Files permissions each grant action stands for. READ needs FILES:READ; WRITE needs both
# FILES:CREATE and FILES:UPDATE, because storage cannot tell creating an object from
# overwriting one; DELETE needs FILES:DELETE. A grant is an explicit choice of what the code
# may do, so a write grant does not imply a read grant.
FILES_PERMISSIONS_BY_ACTION: dict[StorageAction, tuple[Permission, ...]] = {
    StorageAction.READ: (Permission.READ,),
    StorageAction.WRITE: (Permission.CREATE, Permission.UPDATE),
    StorageAction.DELETE: (Permission.DELETE,),
}

# The order permissions are named in.
PERMISSION_ORDER = (Permission.READ, Permission.CREATE, Permission.UPDATE, Permission.DELETE)


def permissions_behind(actions: Iterable[StorageAction]) -> list[Permission]:
    """The FILES permissions the actions stand for, in the order permissions are named."""
    needed = {
        permission for action in actions for permission in FILES_PERMISSIONS_BY_ACTION[action]
    }
    return [permission for permission in PERMISSION_ORDER if permission in needed]


_NO_PERMISSIONS = EffectivePermissions(is_superadmin=False, role=None, by_resource={})


class GrantActor:
    """Whoever writes, and which grant actions their FILES permissions let them hand out.

    Permissions are resolved on first use and then kept, so a bulk save of many nodes
    resolves once.
    """

    def __init__(self, resolve: Callable[[], EffectivePermissions]):
        self._resolve = resolve
        self._effective: EffectivePermissions | None = None

    @classmethod
    def for_request(cls, request) -> "GrantActor":
        """The caller of `request`, in the request's active org."""
        return cls(lambda: resolve_request_permissions(request))

    @classmethod
    def for_user(cls, user, org_id: int) -> "GrantActor":
        """`user` in organization `org_id`; no user, or a non-member, holds nothing."""

        def resolve() -> EffectivePermissions:
            if user is None:
                return _NO_PERMISSIONS
            try:
                return PermissionResolver().resolve(user=user, org_id=org_id)
            except OrgMembershipRequiredError:
                return _NO_PERMISSIONS

        return cls(resolve)

    def held_actions(self) -> frozenset[StorageAction]:
        """The grant actions the actor may hand out."""
        return frozenset(StorageAction) - self.missing(StorageAction)

    def missing_permissions(self, actions: Iterable[StorageAction]) -> list[Permission]:
        """The FILES permissions behind `actions` that the actor lacks, in naming order."""
        wanted = permissions_behind(actions)
        if not wanted:
            return []
        if self._effective is None:
            self._effective = self._resolve()
        return [
            permission
            for permission in wanted
            if not self._effective.can(ResourceType.FILES, permission)
        ]

    def missing(self, actions: Iterable[StorageAction]) -> frozenset[StorageAction]:
        """The actions among `actions` the actor lacks a FILES permission for."""
        wanted = frozenset(actions)
        if not wanted:
            return frozenset()
        if self._effective is None:
            self._effective = self._resolve()
        return frozenset(
            action
            for action in wanted
            if not all(
                self._effective.can(ResourceType.FILES, permission)
                for permission in FILES_PERMISSIONS_BY_ACTION[action]
            )
        )


def grant_actor_for(user, graph) -> GrantActor:
    """`user` as the actor for the nodes created in `graph`, built once per graph object.

    Importing or copying a flow creates many nodes in one graph; keeping the actor on the
    graph resolves the user's permissions once for all of them.
    """
    cached = getattr(graph, "_storage_grant_actor", None)
    if cached is not None and cached[0] is user:
        return cached[1]
    actor = GrantActor.for_user(user, graph.org_id)
    graph._storage_grant_actor = (user, actor)
    return actor
