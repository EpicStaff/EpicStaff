"""Where a grant goes when its plugin's version or state changes: the one rule.

Every path that may move a grant because of its plugin calls `settle_grant`: resume and
reinstall, the start of an upgrade's maintenance, its completion and its cancel, and the
success of an install or upgrade hook. Nothing else decides between `active`, `upgrading` and
`install_failed` for a grant.

The caller holds the plugin's lock (a lifecycle action), or the grant's (a hook result, which
reads the plugin's state after taking it). `settle_grant` sets the grant's state, and its
`installed_version` when it becomes active without a hook; it may create the grant's upgrade
job, which it locks after the grant. The caller saves `SETTLED_FIELDS` and records activity.
"""

from plugins.lifecycle.upgrade_hooks import UpgradeHookService
from plugins.models import GrantState, HookJobKind, HookJobState, PluginGrant, PluginState

SETTLED_FIELDS = ["state", "installed_version", "updated_at"]


def settle_grant(grant: PluginGrant, *, resuming: bool = False) -> str:
    """Move `grant` (loaded with its plugin and current package) to where it belongs now.

    The rules, first match wins:

    1. Resuming only: its install hook ran and has not succeeded → `install_failed`.
    2. The plugin is in maintenance → `upgrading`, with no hook job until it is back.
    3. Its installed version is the current one → `active`.
    4. The current package declares an upgrade hook → `upgrading`, with the grant's open
       upgrade job (created when there is none).
    5. Otherwise → `active`, brought to the current version.

    Returns:
        The state it set.
    """
    plugin = grant.plugin
    if resuming and _install_never_succeeded(grant):
        grant.state = GrantState.INSTALL_FAILED
    elif plugin.state == PluginState.MAINTENANCE:
        grant.state = GrantState.UPGRADING
    elif grant.installed_version == plugin.current_package.version:
        grant.state = GrantState.ACTIVE
    elif _has_upgrade_hook(plugin):
        grant.state = GrantState.UPGRADING
        UpgradeHookService().ensure_job(grant)
    else:
        grant.state = GrantState.ACTIVE
        grant.installed_version = plugin.current_package.version
    return grant.state


def _install_never_succeeded(grant: PluginGrant) -> bool:
    """Whether the grant's latest install job exists and has not succeeded: it was suspended
    during or after a failed install."""
    latest_install = (
        grant.hook_jobs.filter(kind=HookJobKind.INSTALL)
        .order_by("-created_at", "-pk")
        .values_list("state", flat=True)
        .first()
    )
    return latest_install is not None and latest_install != HookJobState.SUCCEEDED


def _has_upgrade_hook(plugin) -> bool:
    manifest = plugin.current_package.parsed_manifest
    return manifest.backend is not None and manifest.hooks.upgrade
