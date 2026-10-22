from dataclasses import dataclass

from plugins.access.plugin_access import accesses_in_organization
from plugins.models import GrantState, Plugin, PluginGrant, PluginState

READY = "ready"
MAINTENANCE = "maintenance"


@dataclass(frozen=True)
class AvailablePlugin:
    """A plugin a person may open in an organization, with their actions on it.

    `availability` is `maintenance` while the plugin is stopped for an upgrade, or the
    organization's upgrade has not finished; the plugin's page then says it is being updated.
    """

    plugin: Plugin
    permissions: list[str]
    availability: str


def plugins_available_to(user, org_id: int) -> list[AvailablePlugin]:
    """Return the plugins `user` may open in organization `org_id`, sorted by name.

    The plugins `plugin_access` lets the person use there, and those it will let them use
    once an upgrade finishes (`PluginGrantQuerySet.listed`): a SuperAdmin who is not a
    member, or a caller that is not a user (the system API key), gets none. At most three
    queries (the third only for a custom role), whatever the number of plugins.
    """
    accesses = accesses_in_organization(
        user, org_id, PluginGrant.objects.filter(org_id=org_id).listed()
    )
    return [
        AvailablePlugin(
            plugin=access.grant.plugin,
            permissions=access.actions,
            availability=MAINTENANCE
            if access.grant.state == GrantState.UPGRADING
            or access.grant.plugin.state == PluginState.MAINTENANCE
            else READY,
        )
        for access in accesses
    ]
