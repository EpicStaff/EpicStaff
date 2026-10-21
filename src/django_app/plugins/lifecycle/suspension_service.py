"""Suspending a plugin in one organization, and resuming it.

A suspended grant holds no keys, so the plugin's backend can no longer call EpicStaff there
and the organization leaves its runtime file; people lose the plugin's page and Roles row;
every run that uses anything the plugin owns there is refused (`plugins.runs.run_guard`), and
the running sessions of such flows are stopped once the suspension commits. Its data stays
until `purge_after`. Resume undoes all of it except the keys: the node's next credentials
fetch mints new ones.

A grant is suspended on its own (`suspension_cause` grant) or because its plugin was
uninstalled (`uninstall`); a reinstall resumes only the second kind. Deleting a grant's data
takes the same steps first when the grant is not suspended yet (`withdraw_access`).

Lock order (`lifecycle_locks`): the plugin, then the grant, then its hook jobs. Keys are
locked through their service account: grant, then account, then keys, the order
`ServiceAccountKeyService.mint_for_plugin` takes the account and its keys in.
"""

from datetime import datetime
from functools import partial

from django.db import transaction
from django.utils import timezone

from plugins.activity.recorder import ActivityRecorder
from plugins.audit import log_grant_resumed, log_grant_suspended
from plugins.configuration.grace_period import grace_period
from plugins.lifecycle.grant_actions import GrantAction, assert_grant_action
from plugins.lifecycle.lifecycle_locks import lock_grant
from plugins.lifecycle.suspended_run_stopper import SuspendedRunStopper
from plugins.models import (
    GrantState,
    HookJobKind,
    HookJobState,
    PluginGrant,
    PluginHookJob,
    PluginServiceAccount,
    PluginServiceAccountKey,
    SuspensionCause,
)
from plugins.models.hook_job import OPEN_HOOK_JOB_STATES

SUSPENDED_BEFORE_HOOK_FINISHED = "Suspended before the hook finished."


class PluginSuspensionService:
    def suspend(self, identifier: str, grant_id: int, actor) -> PluginGrant:
        """Suspend a grant, in one transaction.

        Fails the grant's open hook jobs, keeps the data until now plus the grace period,
        revokes every key of its service account (the account stays) and records the
        activity. Once the transaction commits, the suspension is logged and then the
        organization's running sessions that use what the plugin owns are stopped; a stopper
        that fails is logged and leaves the suspension as it is.

        Raises:
            GrantNotFoundError: No such grant of this plugin.
            GrantNotSuspendableError: The grant's state cannot be suspended.
            PluginUninstallingError: The plugin is uninstalled or being deleted.
        """
        now = timezone.now()
        with transaction.atomic():
            grant = lock_grant(identifier, grant_id)
            assert_grant_action(grant, GrantAction.SUSPEND)
            self.suspend_locked(
                grant,
                actor=actor,
                cause=SuspensionCause.GRANT,
                purge_after=now + grace_period(),
                now=now,
            )
        return grant

    def resume(self, identifier: str, grant_id: int, actor) -> PluginGrant:
        """Resume a suspended grant, in one transaction.

        The grant goes back to `active`, or to `install_failed` when its install hook never
        succeeded. Every key of its service account is revoked again, closing a key minted
        while the suspension committed; the node's next credentials fetch mints new ones.
        `last_hook_error` stays.

        Raises:
            GrantNotFoundError: No such grant of this plugin.
            GrantNotSuspendedError: The grant is not suspended.
            PluginUninstallingError: The plugin is uninstalled or being deleted.
        """
        with transaction.atomic():
            grant = lock_grant(identifier, grant_id)
            assert_grant_action(grant, GrantAction.RESUME)
            self.resume_locked(grant, actor=actor, now=timezone.now())
        log_grant_resumed(actor, grant)
        return grant

    def suspend_locked(
        self, grant: PluginGrant, *, actor, cause: str, purge_after: datetime, now: datetime
    ) -> None:
        """Suspend `grant`, which the caller has locked after its plugin, until `purge_after`.

        Records `grant_suspended` with the cause; after commit, logs it and stops the
        organization's sessions that use what the plugin owns.
        """
        previous_state = grant.state
        withdraw_access(grant, now, hook_error=SUSPENDED_BEFORE_HOOK_FINISHED)
        grant.state = GrantState.SUSPENDED
        grant.suspension_cause = cause
        grant.purge_after = purge_after
        grant.save(
            update_fields=[
                "state",
                "suspended_at",
                "suspension_cause",
                "purge_after",
                "last_hook_error",
                "updated_at",
            ]
        )
        ActivityRecorder().grant_suspended(actor, grant, previous_state, cause)
        transaction.on_commit(partial(log_grant_suspended, actor, grant, previous_state))
        stop_sessions_on_commit(grant)

    def resume_locked(self, grant: PluginGrant, *, actor, now: datetime) -> None:
        """Resume `grant`, suspended and locked after its plugin by the caller.

        Records `grant_resumed` with the cause the suspension had; the caller logs it
        (`log_grant_resumed`) once it has committed.
        """
        cause = grant.suspension_cause
        _revoke_keys(grant, now)
        grant.state = resume_target_state(grant)
        grant.suspended_at = None
        grant.suspension_cause = None
        grant.purge_after = None
        grant.save(
            update_fields=["state", "suspended_at", "suspension_cause", "purge_after", "updated_at"]
        )
        ActivityRecorder().grant_resumed(actor, grant, cause)


def withdraw_access(grant: PluginGrant, now: datetime, *, hook_error: str) -> None:
    """Take away what a grant gives its plugin: the steps every suspension starts with.

    Fails the grant's pending and running hook jobs with `hook_error` (an install job's error
    also becomes the grant's `last_hook_error`), revokes every key of its service account and
    sets `suspended_at`. The caller holds the grant's lock and saves `suspended_at` and
    `last_hook_error` with its own changes.
    """
    _fail_open_hook_jobs(grant, now, hook_error)
    _revoke_keys(grant, now)
    grant.suspended_at = now


def stop_sessions_on_commit(grant: PluginGrant) -> None:
    """Once the transaction commits, stop the organization's open sessions that use what
    `grant`'s plugin owns; a failure is logged and never undoes what committed."""
    organization_id = grant.org_id
    grant_id = grant.pk
    identifier = grant.plugin.identifier

    # A named function, not a `partial`: Django logs a failed robust callback by its
    # `__qualname__`, which a `partial` lacks, and would raise from the handler.
    def stop_affected_sessions() -> None:
        SuspendedRunStopper().stop_for(
            organization_id=organization_id, grant_id=grant_id, plugin_identifier=identifier
        )

    transaction.on_commit(stop_affected_sessions, robust=True)


def resume_target_state(grant: PluginGrant) -> str:
    """The state a suspended grant resumes to: `install_failed` while its install hook has
    not succeeded (it was suspended during or after a failed install), else `active`."""
    latest_install = (
        grant.hook_jobs.filter(kind=HookJobKind.INSTALL)
        .order_by("-created_at", "-pk")
        .values_list("state", flat=True)
        .first()
    )
    if latest_install is not None and latest_install != HookJobState.SUCCEEDED:
        return GrantState.INSTALL_FAILED
    return GrantState.ACTIVE


def _fail_open_hook_jobs(grant: PluginGrant, now: datetime, error: str) -> None:
    """Fail the grant's pending and running hook jobs; locked after the grant."""
    open_jobs = list(
        PluginHookJob.objects.select_for_update()
        .filter(grant=grant, state__in=OPEN_HOOK_JOB_STATES)
        .order_by("pk")
        .only("pk", "kind")
    )
    if not open_jobs:
        return
    PluginHookJob.objects.filter(pk__in=[job.pk for job in open_jobs]).update(
        state=HookJobState.FAILED, finished_at=now, error=error, updated_at=now
    )
    if any(job.kind == HookJobKind.INSTALL for job in open_jobs):
        grant.last_hook_error = error


def _revoke_keys(grant: PluginGrant, now: datetime) -> None:
    """Revoke every key of the grant's service account that is not revoked yet, superseded
    keys still inside their overlap included; the account is locked first (see the module's
    lock order)."""
    list(PluginServiceAccount.objects.select_for_update().filter(grant=grant).values_list("pk"))
    PluginServiceAccountKey.objects.filter(
        service_account__grant=grant, revoked_at__isnull=True
    ).update(revoked_at=now)
