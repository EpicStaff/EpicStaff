from dataclasses import dataclass

from plugins.access.plugin_access import accesses_in_organization
from plugins.models import Plugin, PluginGrant


@dataclass(frozen=True)
class AvailablePlugin:
    """A plugin a person may open in an organization, with their actions on it."""

    plugin: Plugin
    permissions: list[str]


def plugins_available_to(user, org_id: int) -> list[AvailablePlugin]:
    """Return the plugins `user` may open in organization `org_id`, sorted by name.

    Exactly the plugins `plugin_access` lets the person use there: a SuperAdmin who is not a
    member, or a caller that is not a user (the system API key), gets none. At most three
    queries (the third only for a custom role), whatever the number of plugins.
    """
    accesses = accesses_in_organization(
        user, org_id, PluginGrant.objects.filter(org_id=org_id).usable()
    )
    return [
        AvailablePlugin(plugin=access.grant.plugin, permissions=access.actions)
        for access in accesses
    ]
