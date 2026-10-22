"""Which lifecycle actions a plugin allows in its current state: the one place that decides.

The services that act on a plugin call `assert_plugin_action` first; the SuperAdmin's plugin
detail shows `allowed_plugin_actions`, and the frontend offers exactly those buttons. Both
read the plugin's open upgrade, its restore and its pending package (`PluginActionFacts`).

Adding an action: a `PluginLifecycleAction` member, its rule and its refusal below, the
service that calls `assert_plugin_action`, its endpoint, then the frontend's button for it.
Adding a state a plugin can be uninstalled or deleted from: extend
`UNINSTALLABLE_PLUGIN_STATES`.
"""

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from epicstaff_plugin.contracts.versions import is_newer
from utils.exceptions import CustomAPIExeption

from plugins.databases.backup_records import restorable_backups
from plugins.exceptions import (
    PluginNotPurgeableError,
    PluginNotUninstallableError,
    PluginNotUninstallingError,
    PluginNotUpgradableError,
    PluginUninstallingError,
    PluginUpgradeOpenError,
    RemovalNotRetryableError,
    RestoreNotAllowedError,
    UpgradeNotCancellableError,
    UpgradeNotRetryableError,
)
from plugins.lifecycle.open_upgrades import (
    database_changed,
    latest_approved_package,
    open_upgrade_of,
)
from plugins.models import (
    PlacementRemovalState,
    Plugin,
    PluginDatabase,
    PluginDatabaseRestore,
    PluginPackage,
    PluginPlacement,
    PluginState,
    PluginUpgrade,
    ReviewState,
    UpgradeStage,
)
from plugins.models.database import OPEN_RESTORE_STATES


class PluginLifecycleAction(StrEnum):
    UNINSTALL = "uninstall"
    REINSTALL = "reinstall"
    PURGE = "purge"
    RETRY_REMOVAL = "retry_removal"
    UPGRADE = "upgrade"
    CANCEL_UPGRADE = "cancel_upgrade"
    RETRY_UPGRADE = "retry_upgrade"
    RESTORE_BACKUP = "restore_backup"


# A plugin in service. An uploaded plugin is rejected instead; one in maintenance waits for
# its upgrade to finish.
UNINSTALLABLE_PLUGIN_STATES = frozenset(
    {PluginState.PROVISIONING, PluginState.RUNNING, PluginState.FAILED}
)
PURGEABLE_PLUGIN_STATES = UNINSTALLABLE_PLUGIN_STATES | {
    PluginState.UNINSTALLING,
    PluginState.MAINTENANCE,
}
# Uninstalled or being deleted: what the plugin runs can no longer change.
OUT_OF_SERVICE_PLUGIN_STATES = frozenset({PluginState.UNINSTALLING, PluginState.PURGING})
# `PluginActionFacts.of`'s default: the caller has not read the open upgrade.
_NOT_READ = object()
# The states a plugin may start an upgrade from when none is open. Once one is open, whatever
# state its node reports, the upgrade's own rules decide.
UPGRADABLE_PLUGIN_STATES = frozenset({PluginState.RUNNING, PluginState.FAILED})


@dataclass(frozen=True)
class PluginActionFacts:
    """What the action rules read about a plugin besides its state.

    `newer_pending` is whether a pending package is newer than the latest approved version.
    `database_changed` and `restorable_backup` are about the open upgrade, false without one.
    """

    plugin: Plugin
    open_upgrade: PluginUpgrade | None
    restore_open: bool
    database_changed: bool
    restorable_backup: bool
    newer_pending: bool

    @classmethod
    def of(cls, plugin: Plugin, open_upgrade=_NOT_READ) -> "PluginActionFacts":
        """Read the facts of `plugin`: at most two queries without an open upgrade, five with one.

        Pass `open_upgrade` (the upgrade, or None) when the caller has read or locked it
        already; the pending package comes from `with_summary()`'s prefetch when it is there.
        """
        if open_upgrade is _NOT_READ:
            open_upgrade = (
                None if plugin.state in OUT_OF_SERVICE_PLUGIN_STATES else open_upgrade_of(plugin)
            )
        newer_pending = _newer_pending(plugin, open_upgrade)
        if open_upgrade is None:
            return cls(plugin, None, False, False, False, newer_pending)
        database = PluginDatabase.objects.filter(plugin=plugin).only("pk", "ledger").first()
        restore_open = (
            database is not None
            and PluginDatabaseRestore.objects.filter(
                plugin_database=database, state__in=OPEN_RESTORE_STATES
            ).exists()
        )
        restorable = (
            database is not None
            and _restore_conditions_hold(open_upgrade, restore_open=restore_open)
            and restorable_backups(open_upgrade).exists()
        )
        return cls(
            plugin,
            open_upgrade,
            restore_open,
            database_changed(open_upgrade, database),
            restorable,
            newer_pending,
        )


def removal_failed(plugin: Plugin) -> bool:
    """Whether the plugin node reported that removing the plugin failed."""
    try:
        placement = plugin.placement
    except PluginPlacement.DoesNotExist:
        return False
    return placement.removal_state == PlacementRemovalState.FAILED


def restore_allowed(facts: PluginActionFacts) -> bool:
    """Whether the plugin allows a restore now, apart from which backup: its open upgrade
    failed while migrating or starting, and no restore of it is pending or running."""
    upgrade = facts.open_upgrade
    return upgrade is not None and _restore_conditions_hold(
        upgrade, restore_open=facts.restore_open
    )


def upgrade_cancellable(facts: PluginActionFacts) -> bool:
    """Whether the open upgrade can be cancelled: it does not add a backend, no restore of it
    runs, and the database holds no change of the new version yet."""
    upgrade = facts.open_upgrade
    if upgrade is None or upgrade.adds_backend or facts.restore_open:
        return False
    if upgrade.stage in (UpgradeStage.PREPARING, UpgradeStage.MAINTENANCE):
        return True
    return upgrade.failed and not facts.database_changed


def _restore_conditions_hold(upgrade: PluginUpgrade, *, restore_open: bool) -> bool:
    return upgrade.stage == UpgradeStage.MIGRATING and upgrade.failed and not restore_open


def _may_start_upgrade(facts: PluginActionFacts) -> bool:
    """The state part of `upgrade`: no restore runs, and either no upgrade is open and the
    plugin runs (or failed), or the open one failed, so a newer version replaces its target."""
    if facts.restore_open:
        return False
    if facts.open_upgrade is None:
        return facts.plugin.state in UPGRADABLE_PLUGIN_STATES
    return facts.open_upgrade.failed


def _uninstall_refusal(facts: PluginActionFacts) -> type[CustomAPIExeption]:
    if facts.open_upgrade is not None:
        return PluginUpgradeOpenError
    return PluginNotUninstallableError


@dataclass(frozen=True)
class _ActionRule:
    allows: Callable[[PluginActionFacts], bool]
    refusal: Callable[[PluginActionFacts], type[CustomAPIExeption]]


def _always(
    error: type[CustomAPIExeption],
) -> Callable[[PluginActionFacts], type[CustomAPIExeption]]:
    return lambda facts: error


# In the order the actions are listed.
_RULES: dict[PluginLifecycleAction, _ActionRule] = {
    PluginLifecycleAction.UNINSTALL: _ActionRule(
        lambda facts: (
            facts.plugin.state in UNINSTALLABLE_PLUGIN_STATES and facts.open_upgrade is None
        ),
        _uninstall_refusal,
    ),
    PluginLifecycleAction.REINSTALL: _ActionRule(
        lambda facts: facts.plugin.state == PluginState.UNINSTALLING,
        _always(PluginNotUninstallingError),
    ),
    PluginLifecycleAction.UPGRADE: _ActionRule(
        lambda facts: facts.newer_pending and _may_start_upgrade(facts),
        _always(PluginNotUpgradableError),
    ),
    PluginLifecycleAction.CANCEL_UPGRADE: _ActionRule(
        upgrade_cancellable, _always(UpgradeNotCancellableError)
    ),
    PluginLifecycleAction.RETRY_UPGRADE: _ActionRule(
        lambda facts: (
            facts.open_upgrade is not None and facts.open_upgrade.failed and not facts.restore_open
        ),
        _always(UpgradeNotRetryableError),
    ),
    PluginLifecycleAction.RESTORE_BACKUP: _ActionRule(
        lambda facts: facts.restorable_backup, _always(RestoreNotAllowedError)
    ),
    PluginLifecycleAction.PURGE: _ActionRule(
        lambda facts: facts.plugin.state in PURGEABLE_PLUGIN_STATES and not facts.restore_open,
        _always(PluginNotPurgeableError),
    ),
    PluginLifecycleAction.RETRY_REMOVAL: _ActionRule(
        lambda facts: facts.plugin.state == PluginState.PURGING and removal_failed(facts.plugin),
        _always(RemovalNotRetryableError),
    ),
}


def allowed_plugin_actions(
    plugin: Plugin, facts: PluginActionFacts | None = None
) -> list[PluginLifecycleAction]:
    """The actions a SuperAdmin may take on `plugin` now; reads its facts unless given them."""
    facts = facts or PluginActionFacts.of(plugin)
    return [action for action, rule in _RULES.items() if rule.allows(facts)]


def assert_plugin_action(
    plugin: Plugin, action: PluginLifecycleAction, facts: PluginActionFacts | None = None
) -> None:
    """Refuse `action` unless `plugin`'s state allows it.

    For `upgrade` only the state is checked here: whether the package to approve is newer is
    the version rules' (`plugins.packages.version_rules`), which answer with their own error.

    Raises:
        PluginNotUninstallableError: `uninstall` outside provisioning, running and failed.
        PluginUpgradeOpenError: `uninstall` while an upgrade is open.
        PluginNotUninstallingError: `reinstall` of a plugin that is not uninstalled.
        PluginNotUpgradableError: `upgrade` while another upgrade works, a restore runs, or
            from a state that cannot start one.
        UpgradeNotCancellableError: `cancel_upgrade` outside the cancel rule.
        UpgradeNotRetryableError: `retry_upgrade` without a failed open upgrade.
        RestoreNotAllowedError: `restore_backup` outside a failed migration with a backup.
        PluginNotPurgeableError: `purge` of a plugin uploaded, being deleted, or restoring.
        RemovalNotRetryableError: `retry_removal` unless the node reported a failed removal.
    """
    facts = facts or PluginActionFacts.of(plugin)
    rule = _RULES[action]
    allows = _may_start_upgrade if action == PluginLifecycleAction.UPGRADE else rule.allows
    if not allows(facts):
        raise rule.refusal(facts)()


def assert_plugin_in_service(plugin: Plugin) -> None:
    """Refuse a change of what the plugin runs (a new package, an approval, a restart) while
    it is uninstalled or being deleted.

    Raises:
        PluginUninstallingError: The plugin is uninstalled or being deleted.
    """
    if plugin.state in OUT_OF_SERVICE_PLUGIN_STATES:
        raise PluginUninstallingError()


def assert_plugin_not_purging(plugin: Plugin) -> None:
    """Refuse a change of the plugin's settings or limits once it is being deleted; they stay
    editable while it is uninstalled, for a reinstall.

    Raises:
        PluginUninstallingError: The plugin is being deleted.
    """
    if plugin.state == PluginState.PURGING:
        raise PluginUninstallingError()


def _newer_pending(plugin: Plugin, open_upgrade: PluginUpgrade | None) -> bool:
    if plugin.current_package_id is None:
        return False
    pending = getattr(plugin, "pending_packages", None)
    if pending is None:
        pending = list(
            PluginPackage.objects.filter(plugin=plugin, review_state=ReviewState.PENDING).only(
                "id", "version"
            )
        )
    if not pending:
        return False
    return is_newer(pending[0].version, latest_approved_package(plugin, open_upgrade).version)
