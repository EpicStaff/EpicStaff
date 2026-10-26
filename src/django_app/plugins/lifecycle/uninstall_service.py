"""Uninstalling a plugin, and reinstalling it within its grace period.

Uninstall takes the plugin out of service everywhere without deleting anything: every grant
in service is suspended (cause `uninstall`) until the plugin's `purge_after`, its process is
stopped (it runs again only to execute an organization removed hook), and the gateway serves
none of its paths. A reinstall puts it back and resumes exactly the grants the uninstall
suspended; a grant suspended on its own stays suspended. Once `purge_after` passes, the
scheduled maintenance deletes the plugin (`PluginPurgeService`).
"""

from functools import partial

from django.db import transaction
from django.utils import timezone

from plugins.activity.recorder import ActivityRecorder
from plugins.audit import log_grant_resumed, log_plugin_reinstalled, log_plugin_uninstalled
from plugins.configuration.grace_period import grace_period
from plugins.lifecycle.grant_actions import SUSPENDABLE_GRANT_STATES
from plugins.lifecycle.lifecycle_locks import lock_existing_plugin, lock_grants_of
from plugins.lifecycle.plugin_actions import PluginLifecycleAction, assert_plugin_action
from plugins.lifecycle.suspension_service import PluginSuspensionService
from plugins.models import GrantState, Plugin, PluginState, SuspensionCause


class PluginUninstallService:
    def uninstall(self, identifier: str, actor) -> Plugin:
        """Uninstall a plugin, in one transaction.

        The plugin keeps its data until now plus the grace period. Each grant that is being
        granted, active or whose install failed is suspended until then, with the
        suspension's steps (hooks failed, keys revoked, sessions stopped after commit); a
        grant already suspended or being purged keeps its state and dates. A pending package
        stays pending.

        Raises:
            PluginNotFoundError: No such plugin.
            PluginNotUninstallableError: The plugin is not provisioning, running or failed.
        """
        now = timezone.now()
        with transaction.atomic():
            plugin = lock_existing_plugin(identifier)
            assert_plugin_action(plugin, PluginLifecycleAction.UNINSTALL)
            plugin.state = PluginState.UNINSTALLING
            plugin.uninstall_requested_at = now
            plugin.purge_after = now + grace_period()
            plugin.save(
                update_fields=["state", "uninstall_requested_at", "purge_after", "updated_at"]
            )
            suspension = PluginSuspensionService()
            suspended = 0
            for grant in lock_grants_of(plugin):
                if grant.state not in SUSPENDABLE_GRANT_STATES:
                    continue
                suspension.suspend_locked(
                    grant,
                    actor=actor,
                    cause=SuspensionCause.UNINSTALL,
                    purge_after=plugin.purge_after,
                    now=now,
                )
                suspended += 1
            ActivityRecorder().plugin_uninstalled(actor, identifier, plugin.purge_after, suspended)
            transaction.on_commit(
                partial(
                    log_plugin_uninstalled,
                    actor,
                    identifier=identifier,
                    purge_after=plugin.purge_after,
                    grants=suspended,
                )
            )
        return plugin

    def reinstall(self, identifier: str, actor) -> Plugin:
        """Reinstall an uninstalled plugin, in one transaction.

        A plugin with a backend is `provisioning` until its node reports the process running;
        one without is `running` at once. Each grant the uninstall suspended resumes (to
        `active`, or `install_failed` when its install never succeeded), with its keys
        revoked once more; the node's next credentials fetch mints new ones.

        Raises:
            PluginNotFoundError: No such plugin.
            PluginNotUninstallingError: The plugin is not uninstalled.
        """
        now = timezone.now()
        with transaction.atomic():
            plugin = lock_existing_plugin(identifier)
            assert_plugin_action(plugin, PluginLifecycleAction.REINSTALL)
            has_backend = plugin.current_package.parsed_manifest.backend is not None
            plugin.state = PluginState.PROVISIONING if has_backend else PluginState.RUNNING
            plugin.uninstall_requested_at = None
            plugin.purge_after = None
            plugin.save(
                update_fields=["state", "uninstall_requested_at", "purge_after", "updated_at"]
            )
            suspension = PluginSuspensionService()
            resumed = 0
            for grant in lock_grants_of(plugin):
                if (
                    grant.state != GrantState.SUSPENDED
                    or grant.suspension_cause != SuspensionCause.UNINSTALL
                ):
                    continue
                suspension.resume_locked(grant, actor=actor, now=now)
                transaction.on_commit(partial(log_grant_resumed, actor, grant))
                resumed += 1
            ActivityRecorder().plugin_reinstalled(actor, identifier, resumed)
            transaction.on_commit(
                partial(
                    log_plugin_reinstalled, actor, identifier=identifier, grants_resumed=resumed
                )
            )
        return plugin
