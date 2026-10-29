"""`request.user` of a request a plugin's backend makes with its service-account key."""

from rbac.access.effective import EffectivePermissions
from rbac.exceptions import OrgMembershipRequiredError
from tables.models import Secret

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
        development_key: bool,
        person=None,
    ):
        self.service_account_id = service_account_id
        self.grant_id = grant_id
        self.pinned_org_id = pinned_org_id
        self.plugin_identifier = plugin_identifier
        self.display_name = f"{plugin_name} (plugin)"
        self.rate_limit_key = f"plugin-service-account:{service_account_id}"
        self.requests_per_minute = requests_per_minute
        # Authenticated with a development key, through the development API listener.
        self.development_key = development_key
        self.person = person
        self._package = package
        # Secret ids already confirmed as the plugin's own and still existing. The principal
        # lives for one request, so a bulk save of many rows that reference the same secrets
        # asks the database about each id once.
        self._confirmed_own_secret_ids: set[int] = set()

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

    def may_reference_secrets(self, secret_ids: frozenset[int]) -> bool:
        """Only secrets the plugin created under this grant, and that still exist.

        Never the organization's other secrets, whatever access the plugin declares and
        whoever the call is made for: the plugin chooses where a referencing row sends the
        value, so referencing a secret it did not create would hand it the value.
        """
        # Imported here: the ownership modules import this one.
        from plugins.ownership.existing_owned import owned_existing_ids

        unconfirmed = secret_ids - self._confirmed_own_secret_ids
        if not unconfirmed:
            return True
        found = owned_existing_ids(self.grant_id, Secret, unconfirmed)
        self._confirmed_own_secret_ids |= found
        return unconfirmed <= found

    def __str__(self) -> str:
        return f"plugin {self.plugin_identifier} (org {self.pinned_org_id})"
