"""Which lifecycle actions a grant allows in its current state: the one place that decides.

The services that act on a grant call `assert_grant_action` first; the SuperAdmin's grant list
shows `allowed_grant_actions`, and the frontend offers exactly those buttons.

Adding an action: a `GrantAction` member, its rule and its refusal below, the service that
calls `assert_grant_action`, its endpoint, then the frontend's button for it.
"""

from collections.abc import Callable
from enum import StrEnum

from utils.exceptions import CustomAPIExeption

from plugins.exceptions import (
    GrantNotSuspendableError,
    GrantNotSuspendedError,
    HookNotRetryableError,
)
from plugins.models import GrantState, PluginGrant


class GrantAction(StrEnum):
    SUSPEND = "suspend"
    RESUME = "resume"
    RETRY_INSTALL = "retry_install"


# A grant can be suspended while its install hook runs or after it failed, not only once it is
# active, so a SuperAdmin can stop a plugin at any point of its installation.
SUSPENDABLE_GRANT_STATES = frozenset(
    {GrantState.GRANTING, GrantState.ACTIVE, GrantState.INSTALL_FAILED}
)

# In the order the actions are listed.
_RULES: dict[GrantAction, Callable[[PluginGrant], bool]] = {
    GrantAction.RETRY_INSTALL: lambda grant: grant.state == GrantState.INSTALL_FAILED,
    GrantAction.SUSPEND: lambda grant: grant.state in SUSPENDABLE_GRANT_STATES,
    GrantAction.RESUME: lambda grant: grant.state == GrantState.SUSPENDED,
}
_REFUSALS: dict[GrantAction, type[CustomAPIExeption]] = {
    GrantAction.RETRY_INSTALL: HookNotRetryableError,
    GrantAction.SUSPEND: GrantNotSuspendableError,
    GrantAction.RESUME: GrantNotSuspendedError,
}


def allowed_grant_actions(grant: PluginGrant) -> list[GrantAction]:
    """The actions a SuperAdmin may take on `grant` now."""
    return [action for action, allows in _RULES.items() if allows(grant)]


def assert_grant_action(grant: PluginGrant, action: GrantAction) -> None:
    """Refuse `action` unless `grant`'s state allows it.

    Raises:
        HookNotRetryableError: `retry_install` on a grant whose install hook has not failed.
        GrantNotSuspendableError: `suspend` on a grant that cannot be suspended.
        GrantNotSuspendedError: `resume` on a grant that is not suspended.
    """
    if not _RULES[action](grant):
        raise _REFUSALS[action]()
