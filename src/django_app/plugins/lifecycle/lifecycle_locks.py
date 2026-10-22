"""The row locks the plugin lifecycle takes, in the one order all of it follows.

Every lifecycle action locks the plugin first, then its open upgrade, then that upgrade's
restore, then the placement, then the plugin's database record, then its grants (in ascending
pk), then hook jobs, then backups, then ownership rows. Package rows are locked only under the
plugin's lock. A per-grant action (suspend, resume, retry a hook, delete a grant's data)
therefore never races an uninstall, an upgrade or a plugin's deletion, and none of them can
deadlock another. Paths that keep an order of their own: the node's claim and result lock a
job's grant, then the job, never the plugin; a node report locks placements, then database
records, then backups, and takes the plugin only in its follow-up transaction, which locks
nothing before it; an organization's deletion locks organizations, then their grants.

The plugin row is locked `FOR NO KEY UPDATE`: an organization's deletion inserts hook jobs
that point at the plugin, and Postgres takes `FOR KEY SHARE` on the plugin for each at
commit. A full `FOR UPDATE` here would wait on that commit while it waits on a grant this
path holds.
"""

from plugins.exceptions import GrantNotFoundError, PluginNotFoundError
from plugins.models import Plugin, PluginGrant


def lock_plugin(identifier: str, *, skip_locked: bool = False) -> Plugin | None:
    """Lock the plugin row, with its current package (not locked, without its icon); None
    when there is none, or when `skip_locked` and another process holds it."""
    return (
        Plugin.objects.select_for_update(of=("self",), no_key=True, skip_locked=skip_locked)
        .select_related("current_package")
        .defer("current_package__icon_bytes")
        .filter(identifier=identifier)
        .first()
    )


def lock_existing_plugin(identifier: str) -> Plugin:
    """`lock_plugin`, for a plugin that must exist.

    Raises:
        PluginNotFoundError: No such plugin.
    """
    plugin = lock_plugin(identifier)
    if plugin is None:
        raise PluginNotFoundError()
    return plugin


def lock_grant(identifier: str, grant_id: int) -> PluginGrant:
    """Lock the plugin, then its grant `grant_id`, which comes with that plugin and its
    organization.

    Raises:
        GrantNotFoundError: No such plugin, or no such grant of it.
    """
    plugin = lock_plugin(identifier)
    if plugin is None:
        raise GrantNotFoundError()
    grant = (
        PluginGrant.objects.select_for_update(of=("self",))
        .select_related("org")
        .filter(pk=grant_id, plugin=plugin)
        .first()
    )
    if grant is None:
        raise GrantNotFoundError()
    grant.plugin = plugin
    return grant


def lock_grants_of(plugin: Plugin) -> list[PluginGrant]:
    """Lock every grant of `plugin` (locked already), in ascending pk, each with its organization."""
    grants = list(
        PluginGrant.objects.select_for_update(of=("self",))
        .select_related("org")
        .filter(plugin=plugin)
        .order_by("pk")
    )
    for grant in grants:
        grant.plugin = plugin
    return grants
