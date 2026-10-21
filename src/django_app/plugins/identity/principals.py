"""`request.user` of a request a plugin's backend makes with its service-account key."""

from rbac.access.effective import EffectivePermissions
from rbac.exceptions import OrgMembershipRequiredError

from plugins.access.declared_access import package_declared_access_bits
from plugins.models import PluginPackage


class PluginServiceAccountPrincipal:
    """A plugin's service account in the one organization its grant is to.

    Implements `rbac.access.principals.PinnedOrgPrincipal`: rbac resolves its permissions in
    `pinned_org_id` to the plugin's declared access, and treats every other organization as
    one it is not a member of. It is not a `User` and deliberately has no `id`, `pk`, `email`,
    `username` or `is_active`, so code that would store it as a person, an author or an
    editor fails instead of picking a wrong user. The person a call is made for, when the
    plugin names one and may, is `person`.
    """

    is_authenticated = True
    is_anonymous = False
    is_superadmin = False
    is_plugin_credential = True

    def __init__(
        self,
        *,
        service_account_id: int,
        grant_id: int,
        pinned_org_id: int,
        plugin_identifier: str,
        plugin_name: str,
        package: PluginPackage,
        requests_per_minute: int,
        person=None,
    ):
        self.service_account_id = service_account_id
        self.grant_id = grant_id
        self.pinned_org_id = pinned_org_id
        self.plugin_identifier = plugin_identifier
        self.display_name = f"{plugin_name} (plugin)"
        self.rate_limit_key = f"plugin-service-account:{service_account_id}"
        self.requests_per_minute = requests_per_minute
        self.person = person
        self._package = package

    def resolve_effective_permissions(self, org_id: int) -> EffectivePermissions:
        """The plugin's declared access in the pinned organization; no rights anywhere else.

        Raises:
            OrgMembershipRequiredError: `org_id` is not the pinned organization.
        """
        if org_id != self.pinned_org_id:
            raise OrgMembershipRequiredError()
        return EffectivePermissions(
            is_superadmin=False,
            role=None,
            by_resource=package_declared_access_bits.get(self._package),
        )

    def __str__(self) -> str:
        return f"plugin {self.plugin_identifier} (org {self.pinned_org_id})"
