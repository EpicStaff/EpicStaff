"""Which lifecycle actions a grant allows in its current state: the one place that decides.

A grant's actions depend on its own state and on its plugin's: while the plugin is uninstalled
a grant's data can only be deleted, and while the plugin is being deleted nothing more can be
done to a grant. The services that act on a grant call `assert_grant_action` first; the
SuperAdmin's grant list shows `allowed_grant_actions`, and the frontend offers exactly those
buttons. Both read `grant.plugin`, so load it with the grant.

Adding an action: a `GrantAction` member, its rule below, the service that calls
`assert_grant_action`, its endpoint, then the frontend's button for it. Adding a state a
grant can be suspended or purged from: extend `SUSPENDABLE_GRANT_STATES` (a grant is purged
from every suspendable state, and from `suspended`).
"""

from dataclasses import dataclass
from enum import StrEnum

from utils.exceptions import CustomAPIExeption

from plugins.exceptions import (
    GrantNotPurgeableError,
    GrantNotSuspendableError,
    GrantNotSuspendedError,
    HookNotRetryableError,
    PluginUninstallingError,
)
from plugins.lifecycle.plugin_actions import OUT_OF_SERVICE_PLUGIN_STATES
from plugins.models import GrantState, PluginGrant, PluginState


class GrantAction(StrEnum):
    SUSPEND = "suspend"
    RESUME = "resume"
    RETRY_INSTALL = "retry_install"
    RETRY_UPGRADE = "retry_upgrade"
    PURGE = "purge"


# A grant can be suspended while its install or upgrade hook runs or after it failed, not only
# once it is active, so a SuperAdmin can stop a plugin at any point of its installation.
SUSPENDABLE_GRANT_STATES = frozenset(
    {
        GrantState.GRANTING,
        GrantState.ACTIVE,
        GrantState.INSTALL_FAILED,
        GrantState.UPGRADING,
        GrantState.UPGRADE_FAILED,
    }
)
PURGEABLE_GRANT_STATES = SUSPENDABLE_GRANT_STATES | {GrantState.SUSPENDED}


@dataclass(frozen=True)
class _ActionRule:
    """The grant states an action needs, the plugin states that refuse it whatever the grant's
    state, and the error for each refusal."""

    grant_states: frozenset[str]
    refused_by_grant: type[CustomAPIExeption]
    blocking_plugin_states: frozenset[str]
    refused_by_plugin: type[CustomAPIExeption]


# In the order the actions are listed.
_RULES: dict[GrantAction, _ActionRule] = {
    GrantAction.RETRY_INSTALL: _ActionRule(
        frozenset({GrantState.INSTALL_FAILED}),
        HookNotRetryableError,
        OUT_OF_SERVICE_PLUGIN_STATES,
        PluginUninstallingError,
    ),
    GrantAction.RETRY_UPGRADE: _ActionRule(
        frozenset({GrantState.UPGRADE_FAILED}),
        HookNotRetryableError,
        OUT_OF_SERVICE_PLUGIN_STATES,
        PluginUninstallingError,
    ),
    GrantAction.SUSPEND: _ActionRule(
        SUSPENDABLE_GRANT_STATES,
        GrantNotSuspendableError,
        OUT_OF_SERVICE_PLUGIN_STATES,
        PluginUninstallingError,
    ),
    GrantAction.RESUME: _ActionRule(
        frozenset({GrantState.SUSPENDED}),
        GrantNotSuspendedError,
        OUT_OF_SERVICE_PLUGIN_STATES,
        PluginUninstallingError,
    ),
    GrantAction.PURGE: _ActionRule(
        PURGEABLE_GRANT_STATES,
        GrantNotPurgeableError,
        frozenset({PluginState.PURGING}),
        GrantNotPurgeableError,
    ),
}


def allowed_grant_actions(grant: PluginGrant) -> list[GrantAction]:
    """The actions a SuperAdmin may take on `grant` now."""
    return [
        action
        for action, rule in _RULES.items()
        if grant.state in rule.grant_states
        and grant.plugin.state not in rule.blocking_plugin_states
    ]


def assert_grant_action(grant: PluginGrant, action: GrantAction) -> None:
    """Refuse `action` unless `grant`'s state and its plugin's allow it.

    Raises:
        HookNotRetryableError: `retry_install` or `retry_upgrade` on a grant whose install or
            upgrade hook has not failed.
        GrantNotSuspendableError: `suspend` on a grant that cannot be suspended.
        GrantNotSuspendedError: `resume` on a grant that is not suspended.
        GrantNotPurgeableError: `purge` on a grant, or of a plugin, already being deleted.
        PluginUninstallingError: `suspend`, `resume`, `retry_install` or `retry_upgrade` while
            the plugin is uninstalled or being deleted.
    """
    rule = _RULES[action]
    if grant.state not in rule.grant_states:
        raise rule.refused_by_grant()
    if grant.plugin.state in rule.blocking_plugin_states:
        raise rule.refused_by_plugin()
