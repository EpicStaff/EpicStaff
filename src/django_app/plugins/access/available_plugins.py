from dataclasses import dataclass

from plugins.access.plugin_access import accesses_in_organization
from plugins.development.development_targets import served_from_development
from plugins.models import GrantState, Plugin, PluginGrant, PluginState

READY = "ready"
MAINTENANCE = "maintenance"


@dataclass(frozen=True)
class AvailablePlugin:
    """A plugin a person may open in an organization, with their actions on it.

    `availability` is `maintenance` while the plugin is stopped for an upgrade, or the
    organization's upgrade has not finished; the plugin's page then says it is being updated.
    `development` is true while development mode serves some part of it from a developer's
    machine, never while it is in maintenance; a member never sees where.
    """

    plugin: Plugin
    permissions: list[str]
    availability: str
    development: bool


def plugins_available_to(user, org_id: int) -> list[AvailablePlugin]:
    """Return the plugins `user` may open in organization `org_id`, sorted by name.

    The plugins `plugin_access` lets the person use there, and those it will let them use
    once an upgrade finishes (`PluginGrantQuerySet.listed`): a SuperAdmin who is not a
    member, or a caller that is not a user (the system API key), gets none. At most three
    queries (the third only for a custom role), whatever the number of plugins.
    """
    accesses = accesses_in_organization(
        user,
        org_id,
        PluginGrant.objects.filter(org_id=org_id)
        .listed()
        .select_related("plugin__development_target"),
    )
    return [_available(access.grant, access.actions) for access in accesses]


def _available(grant: PluginGrant, permissions: list[str]) -> AvailablePlugin:
    plugin = grant.plugin
    in_maintenance = grant.state == GrantState.UPGRADING or plugin.state == PluginState.MAINTENANCE
    return AvailablePlugin(
        plugin=plugin,
        permissions=permissions,
        availability=MAINTENANCE if in_maintenance else READY,
        development=not in_maintenance and served_from_development(plugin),
    )
