"""Which lifecycle actions a plugin allows in its current state: the one place that decides.

The services that act on a plugin call `assert_plugin_action` first; the SuperAdmin's plugin
detail shows `allowed_plugin_actions`, and the frontend offers exactly those buttons.

Adding an action: a `PluginLifecycleAction` member, its rule and its refusal below, the
service that calls `assert_plugin_action`, its endpoint, then the frontend's button for it.
Adding a state a plugin can be uninstalled or deleted from: extend
`UNINSTALLABLE_PLUGIN_STATES`.
"""

from collections.abc import Callable
from enum import StrEnum

from utils.exceptions import CustomAPIExeption

from plugins.exceptions import (
    PluginNotPurgeableError,
    PluginNotUninstallableError,
    PluginNotUninstallingError,
    PluginUninstallingError,
    RemovalNotRetryableError,
)
from plugins.models import PlacementRemovalState, Plugin, PluginPlacement, PluginState


class PluginLifecycleAction(StrEnum):
    UNINSTALL = "uninstall"
    REINSTALL = "reinstall"
    PURGE = "purge"
    RETRY_REMOVAL = "retry_removal"


# A plugin in service. An uploaded plugin is rejected instead; one in maintenance waits for
# its upgrade to finish.
UNINSTALLABLE_PLUGIN_STATES = frozenset(
    {PluginState.PROVISIONING, PluginState.RUNNING, PluginState.FAILED}
)
PURGEABLE_PLUGIN_STATES = UNINSTALLABLE_PLUGIN_STATES | {PluginState.UNINSTALLING}
# Uninstalled or being deleted: what the plugin runs can no longer change.
OUT_OF_SERVICE_PLUGIN_STATES = frozenset({PluginState.UNINSTALLING, PluginState.PURGING})


def removal_failed(plugin: Plugin) -> bool:
    """Whether the plugin node reported that removing the plugin failed."""
    try:
        placement = plugin.placement
    except PluginPlacement.DoesNotExist:
        return False
    return placement.removal_state == PlacementRemovalState.FAILED


# In the order the actions are listed.
_RULES: dict[PluginLifecycleAction, Callable[[Plugin], bool]] = {
    PluginLifecycleAction.UNINSTALL: lambda plugin: plugin.state in UNINSTALLABLE_PLUGIN_STATES,
    PluginLifecycleAction.REINSTALL: lambda plugin: plugin.state == PluginState.UNINSTALLING,
    PluginLifecycleAction.PURGE: lambda plugin: plugin.state in PURGEABLE_PLUGIN_STATES,
    PluginLifecycleAction.RETRY_REMOVAL: lambda plugin: (
        plugin.state == PluginState.PURGING and removal_failed(plugin)
    ),
}
_REFUSALS: dict[PluginLifecycleAction, type[CustomAPIExeption]] = {
    PluginLifecycleAction.UNINSTALL: PluginNotUninstallableError,
    PluginLifecycleAction.REINSTALL: PluginNotUninstallingError,
    PluginLifecycleAction.PURGE: PluginNotPurgeableError,
    PluginLifecycleAction.RETRY_REMOVAL: RemovalNotRetryableError,
}


def allowed_plugin_actions(plugin: Plugin) -> list[PluginLifecycleAction]:
    """The actions a SuperAdmin may take on `plugin` now; reads its placement for a removal."""
    return [action for action, allows in _RULES.items() if allows(plugin)]


def assert_plugin_action(plugin: Plugin, action: PluginLifecycleAction) -> None:
    """Refuse `action` unless `plugin`'s state allows it.

    Raises:
        PluginNotUninstallableError: `uninstall` outside provisioning, running and failed.
        PluginNotUninstallingError: `reinstall` of a plugin that is not uninstalled.
        PluginNotPurgeableError: `purge` of a plugin uploaded, in maintenance or being deleted.
        RemovalNotRetryableError: `retry_removal` unless the node reported a failed removal.
    """
    if not _RULES[action](plugin):
        raise _REFUSALS[action]()


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
