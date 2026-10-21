"""What a storage write request may do with the org's storage recycle bin when it doesn't fit."""

from dataclasses import dataclass

from rbac.access.principals import is_plugin_credential
from rbac.access.resolver import PermissionResolver
from rbac.models.api_key import ApiKey
from rbac.models.enums import Permission, ResourceType
from tables.services.storage_service.dataclasses import BinPurgeGrant, PurgedBinEntry
from tables.views.recycle_bin_mixins import request_actor

_resolver = PermissionResolver()


@dataclass(frozen=True, slots=True)
class StorageBinPurgeAccess:
    """A write request's say over the destination org's storage bin, decided from its auth.

    A write that doesn't fit the quota purges the org's oldest bin entries only for a user
    session holding FILES DELETE in that org (`grant`): purging can't be undone, so
    neither a role without DELETE nor a possibly leaked API key or plugin credential may
    cause one. Everyone else gets the 413, the bin counted as used. The response names the
    purged entries only to a caller holding FILES READ there; to anyone else it shows their
    sizes alone.
    """

    grant: BinPurgeGrant | None
    names_visible: bool

    @classmethod
    def for_request(cls, request, org_id: int) -> "StorageBinPurgeAccess":
        """Decide for an authenticated, authorized request writing into `org_id`.

        The caller must already be a member of `org_id` or a superadmin: the view's
        permission gate (or the cross-org superadmin check) has run before this.
        """
        # An API key or a plugin credential never purges, so nothing purged is ever
        # shown to it either.
        if isinstance(request.auth, ApiKey) or is_plugin_credential(request):
            return cls(grant=None, names_visible=False)
        permissions = _resolver.resolve(user=request.user, org_id=org_id)
        may_purge = permissions.can(ResourceType.FILES, Permission.DELETE)
        return cls(
            grant=BinPurgeGrant(actor=request_actor(request)) if may_purge else None,
            names_visible=permissions.can(ResourceType.FILES, Permission.READ),
        )

    def render(self, purged: list[PurgedBinEntry]) -> list[dict]:
        """The `recycle_bin_purged` list of the response."""
        return [
            {"name": entry.name if self.names_visible else None, "size": entry.size}
            for entry in purged
        ]
