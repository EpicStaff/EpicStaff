"""A plugin's open upgrade, and what follows from it.

`node_package` is the package the plugin's node runs: the upgrade's target once the plugin
is stopped for it (`maintenance` and `migrating`), the current package otherwise. Everything
the node acts on (the desired package, runtime, database and egress, the runtime file, the
settings and limits the SuperAdmin edits) comes from it.
"""

from plugins.models import Plugin, PluginDatabase, PluginPackage, PluginUpgrade
from plugins.models.upgrade import OPEN_UPGRADE_STAGES, TARGET_STAGES

# The package being upgraded from is read only by `database_changed`, for an upgrade without a
# ledger snapshot, which loads its migration files when it needs them.
_COLUMNS_NOT_READ = (
    "to_package__icon_bytes",
    "from_package__icon_bytes",
    "from_package__manifest",
    "from_package__migration_files",
)


def open_upgrades():
    """Every open upgrade, with its target package (without its icon) and the version it
    upgrades from (without its icon, manifest and migration files)."""
    return (
        PluginUpgrade.objects.filter(stage__in=OPEN_UPGRADE_STAGES)
        .select_related("to_package", "from_package")
        .defer(*_COLUMNS_NOT_READ)
    )


def open_upgrade_of(plugin: Plugin, *, lock: bool = False) -> PluginUpgrade | None:
    """The plugin's open upgrade, if any; `lock` locks its row (take the plugin's lock first).

    The lock is `FOR NO KEY UPDATE`: a backup the node reports for the upgrade points at it,
    and its insert takes `FOR KEY SHARE` on the upgrade at commit, which a full `FOR UPDATE`
    would make wait on this transaction while it waits on the report's rows.
    """
    upgrades = open_upgrades().filter(plugin=plugin)
    if lock:
        upgrades = upgrades.select_for_update(of=("self",), no_key=True)
    return upgrades.first()


def node_package(plugin: Plugin, upgrade: PluginUpgrade | None) -> PluginPackage | None:
    """The package `plugin`'s node runs, given its open upgrade (or None)."""
    if upgrade is not None and upgrade.stage in TARGET_STAGES:
        return upgrade.to_package
    return plugin.current_package


def latest_approved_package(plugin: Plugin, upgrade: PluginUpgrade | None) -> PluginPackage:
    """The package a new version is compared with: the open upgrade's target, else the
    current package."""
    if upgrade is not None:
        return upgrade.to_package
    return plugin.current_package


def database_changed(upgrade: PluginUpgrade, database: PluginDatabase | None) -> bool:
    """Whether the database already holds a change of the upgrade's new version.

    False before the upgrade's first migration run. Then true when the database's reported
    ledger lists a file, or a file with another sha256, that it did not list when the node
    first asked to run the migrations (`ledger_at_migrations`): a file an earlier version
    dropped but the database still lists counts as no change.

    An upgrade that adds a backend has no snapshot: it starts in `migrating` and the node never
    asks to run its migrations. Its ledger is compared with the migration files of the version
    it upgrades from instead, a version without a backend and so without a database: every
    file the new database lists is a change.
    """
    if database is None or upgrade.migrations_started_at is None:
        return False
    if upgrade.ledger_at_migrations is not None:
        known = {(entry["name"], entry["sha256"]) for entry in upgrade.ledger_at_migrations}
    else:
        # An upgrade that adds a backend. A missing `from_package` counts every entry as a
        # change too, so nothing is cancelled on a ledger it cannot be compared with.
        source = upgrade.from_package
        known = {
            (file["name"], file["sha256"])
            for file in (source.migration_files if source is not None else [])
        }
    return any((entry["name"], entry["sha256"]) not in known for entry in database.ledger)
