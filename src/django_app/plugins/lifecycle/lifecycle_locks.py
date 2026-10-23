"""The row locks the plugin lifecycle takes, in the one order all of it follows.

Every lifecycle action locks the plugin first, then its open upgrade, then that upgrade's
restore, then the placement, then the plugin's database record, then its grants (in ascending
pk), then hook jobs, then the grants' service accounts (in organization order), then those
accounts' keys, then backups, then ownership rows. Keys are locked only through their
account: an UPDATE of them once the account is locked. Package rows are locked only under the
plugin's lock. A per-grant action (suspend, resume, retry a hook, delete a grant's data)
therefore never races an uninstall, an upgrade or a plugin's deletion, and none of them can
deadlock another.

Paths that keep an order of their own:

- the node's claim and result lock a job's grant, then the job, never the plugin;
- the node's credentials fetch locks the plugin's grants, then their service accounts, then
  their keys (`ServiceAccountKeyService.mint_for_plugin`), never the plugin;
- a node report locks placements, then database records, then backups, then the restore a
  pre-restore backup belongs to (`BackupRecorder`), and takes the plugin only in its
  follow-up transaction, which locks nothing before it;
- an organization's deletion locks organizations, then their grants, then deletes the
  grants' service accounts and keys with them.

Every row that new rows point at is locked `FOR NO KEY UPDATE`, never `FOR UPDATE`: the
plugin (an organization's deletion inserts hook jobs that point at it), the open upgrade, the
database record and its backups (a node's report and its `migrations` request insert backups
that point at them), and a restore. Postgres takes `FOR KEY SHARE` on the row an inserted
foreign key names, at the insert's commit; a full `FOR UPDATE` would make that commit wait on
this transaction while this one waits on a row the inserting one holds. No path updates a key
column of these rows; one that did would need `FOR UPDATE`. Deleting a plugin (its removal, or
the rejection of its first package) takes `FOR UPDATE` by itself, once nothing inserts rows
that point at it any more.

Grants are the exception: they are locked `FOR UPDATE` although service accounts, hook jobs,
role actions and ownership rows point at them. The lifecycle inserts such rows only for a
grant it holds already (an approval's service accounts, `settle_grant`'s upgrade jobs, an
organization's deletion's organization removed jobs). The other inserters, a role save
writing a role's plugin actions under the role's lock and a plugin's API request recording
what it created, hold no row a lifecycle action locks after a grant, so a grant's holder never
waits on them while they wait on it. An organization's deletion is the one holder that goes
on to such a row (it deletes the organization's roles); it deletes the grants as well, so no
weaker lock would let the insert through, and Postgres rolls one of the two back if a role
save meets it.
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
    """Lock every grant of `plugin`, in ascending pk, each with its organization.

    A lifecycle action locks the plugin first; the node's credentials fetch locks the grants
    without it (see the module's lock order).
    """
    grants = list(
        PluginGrant.objects.select_for_update(of=("self",))
        .select_related("org")
        .filter(plugin=plugin)
        .order_by("pk")
    )
    for grant in grants:
        grant.plugin = plugin
    return grants
