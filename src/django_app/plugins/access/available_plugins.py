from dataclasses import dataclass

from epicstaff_plugin.contracts.manifest import NavigationItem

from plugins.access.plugin_access import accesses_in_organization
from plugins.development.development_targets import served_from_development
from plugins.gateway.host_verifier import PluginHostVerifier
from plugins.models import GrantState, Plugin, PluginGrant, PluginState

READY = "ready"
MAINTENANCE = "maintenance"
UNAVAILABLE = "unavailable"
AVAILABILITIES = (READY, MAINTENANCE, UNAVAILABLE)


@dataclass(frozen=True)
class AvailablePlugin:
    """A plugin a person may open in an organization, with their actions on it.

    `availability` is `maintenance` while the plugin is stopped for an upgrade, or the
    organization's upgrade has not finished; the plugin's page then says it is being updated.
    It is `unavailable` when the plugin's host does not prove it is served by this deployment
    (`PluginHostVerifier`): EpicStaff must not frame it, as another server holds that name.
    `development` is true while development mode serves some part of it from a developer's
    machine, never while it is in maintenance or unavailable; a member never sees where.
    """

    plugin: Plugin
    permissions: list[str]
    availability: str
    development: bool

    @property
    def visible_navigation(self) -> list[NavigationItem]:
        """The running version's app menu entries this person sees, in the manifest's order.

        An entry that names a `permission` shows only when it is among `permissions`, the
        person's actions in this organization. Hiding an entry is not access control: its page
        stays reachable by its path, so the plugin checks the permission there itself.
        """
        spa = self.plugin.current_package.parsed_manifest.spa
        if spa is None:
            return []
        return [
            item
            for item in spa.navigation
            if item.permission is None or item.permission in self.permissions
        ]


def plugins_available_to(user, org_id: int) -> list[AvailablePlugin]:
    """Return the plugins `user` may open in organization `org_id`, sorted by name.

    The plugins `plugin_access` lets the person use there, and those it will let them use
    once an upgrade finishes (`PluginGrantQuerySet.listed`): a SuperAdmin who is not a
    member, or a caller that is not a user (the system API key), gets none. At most three
    queries (the third only for a custom role), whatever the number of plugins.

    A plugin whose host does not prove it is served by this deployment is `unavailable`
    (`PluginHostVerifier`: one request per plugin host at most once a minute, cached; none
    for a plugin in maintenance, which is not framed either).
    """
    hosts = PluginHostVerifier()
    accesses = accesses_in_organization(
        user,
        org_id,
        PluginGrant.objects.filter(org_id=org_id)
        .listed()
        .select_related("plugin__development_target"),
    )
    return [_available(access.grant, access.actions, hosts) for access in accesses]


def _available(
    grant: PluginGrant, permissions: list[str], hosts: PluginHostVerifier
) -> AvailablePlugin:
    plugin = grant.plugin
    in_maintenance = grant.state == GrantState.UPGRADING or plugin.state == PluginState.MAINTENANCE
    if in_maintenance:
        availability = MAINTENANCE
    elif hosts.is_served_here(plugin.identifier):
        availability = READY
    else:
        availability = UNAVAILABLE
    return AvailablePlugin(
        plugin=plugin,
        permissions=permissions,
        availability=availability,
        development=availability == READY and served_from_development(plugin),
    )
