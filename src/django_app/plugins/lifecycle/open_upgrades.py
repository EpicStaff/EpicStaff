"""A plugin's open upgrade, and what follows from it.

`node_package` is the package the plugin's node runs: the upgrade's target once the plugin
is stopped for it (`maintenance` and `migrating`), the current package otherwise. Everything
the node acts on (the desired package, runtime, database and egress, the runtime file, the
settings and limits the SuperAdmin edits) comes from it.
"""

from plugins.models import Plugin, PluginDatabase, PluginPackage, PluginUpgrade
from plugins.models.upgrade import OPEN_UPGRADE_STAGES, TARGET_STAGES

_PACKAGE_COLUMNS_NOT_READ = ("icon_bytes",)


def open_upgrades():
    """Every open upgrade, each with its two packages (without their icons)."""
    return (
        PluginUpgrade.objects.filter(stage__in=OPEN_UPGRADE_STAGES)
        .select_related("to_package", "from_package")
        .defer(
            *(
                f"{package}__{column}"
                for package in ("to_package", "from_package")
                for column in _PACKAGE_COLUMNS_NOT_READ
            )
        )
    )


def open_upgrade_of(plugin: Plugin, *, lock: bool = False) -> PluginUpgrade | None:
    """The plugin's open upgrade, if any; `lock` locks its row (take the plugin's lock first)."""
    upgrades = open_upgrades().filter(plugin=plugin)
    if lock:
        upgrades = upgrades.select_for_update(of=("self",))
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

    True when its reported ledger lists a file the version being upgraded from does not have,
    or with another sha256. A missing `from_package` counts every entry as a change, so
    nothing is cancelled on a ledger it cannot be compared with.
    """
    if database is None:
        return False
    known = {
        (file["name"], file["sha256"])
        for file in (upgrade.from_package.migration_files if upgrade.from_package else [])
    }
    return any((entry["name"], entry["sha256"]) not in known for entry in database.ledger)
