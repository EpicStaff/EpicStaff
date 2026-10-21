"""Suspending a plugin in one organization, and resuming it.

A suspended grant holds no keys, so the plugin's backend can no longer call EpicStaff there
and the organization leaves its runtime file; people lose the plugin's page and Roles row;
every run that uses anything the plugin owns there is refused (`plugins.runs.run_guard`), and
the running sessions of such flows are stopped once the suspension commits. Its data stays
until `purge_after`. Resume undoes all of it except the keys: the node's next credentials
fetch mints new ones.

Lock order: a service that changes a grant and its hook jobs locks the grant first, then the
jobs (as `HookJobService` does), so a suspension and a hook result never deadlock. Keys are
locked through their service account: grant, then account, then keys, the order
`ServiceAccountKeyService.mint_for_plugin` takes the account and its keys in.
"""

from functools import partial

from django.db import transaction
from django.utils import timezone

from plugins.activity.recorder import ActivityRecorder
from plugins.audit import log_grant_resumed, log_grant_suspended
from plugins.configuration.grace_period import grace_period
from plugins.exceptions import GrantNotFoundError
from plugins.lifecycle.grant_actions import GrantAction, assert_grant_action
from plugins.lifecycle.suspended_run_stopper import SuspendedRunStopper
from plugins.models import (
    GrantState,
    HookJobKind,
    HookJobState,
    PluginGrant,
    PluginHookJob,
    PluginServiceAccount,
    PluginServiceAccountKey,
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
        """
        now = timezone.now()
        with transaction.atomic():
            grant = _locked_grant(identifier, grant_id)
            assert_grant_action(grant, GrantAction.SUSPEND)
            previous_state = grant.state
            _fail_open_hook_jobs(grant, now)
            grant.state = GrantState.SUSPENDED
            grant.suspended_at = now
            grant.purge_after = now + grace_period()
            grant.save(
                update_fields=[
                    "state",
                    "suspended_at",
                    "purge_after",
                    "last_hook_error",
                    "updated_at",
                ]
            )
            _revoke_keys(grant, now)
            ActivityRecorder().grant_suspended(actor, grant, previous_state)
            transaction.on_commit(partial(log_grant_suspended, actor, grant, previous_state))

            # A named function, not a `partial`: Django logs a failed robust callback by its
            # `__qualname__`, which a `partial` lacks, and would raise from the handler.
            def stop_affected_sessions() -> None:
                SuspendedRunStopper().stop_for(
                    organization_id=grant.org_id,
                    grant_id=grant.pk,
                    plugin_identifier=identifier,
                )

            transaction.on_commit(stop_affected_sessions, robust=True)
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
        """
        now = timezone.now()
        with transaction.atomic():
            grant = _locked_grant(identifier, grant_id)
            assert_grant_action(grant, GrantAction.RESUME)
            _revoke_keys(grant, now)
            grant.state = resume_target_state(grant)
            grant.suspended_at = None
            grant.purge_after = None
            grant.save(update_fields=["state", "suspended_at", "purge_after", "updated_at"])
            ActivityRecorder().grant_resumed(actor, grant)
        log_grant_resumed(actor, grant)
        return grant


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


def _locked_grant(identifier: str, grant_id: int) -> PluginGrant:
    grant = (
        PluginGrant.objects.select_for_update(of=("self",))
        .select_related("plugin")
        .filter(pk=grant_id, plugin__identifier=identifier)
        .first()
    )
    if grant is None:
        raise GrantNotFoundError()
    return grant


def _fail_open_hook_jobs(grant: PluginGrant, now) -> None:
    """Fail the grant's pending and running hook jobs; locked after the grant."""
    open_jobs = list(
        PluginHookJob.objects.select_for_update()
        .filter(grant=grant, state__in=OPEN_HOOK_JOB_STATES)
        .only("pk", "kind")
    )
    if not open_jobs:
        return
    PluginHookJob.objects.filter(pk__in=[job.pk for job in open_jobs]).update(
        state=HookJobState.FAILED,
        finished_at=now,
        error=SUSPENDED_BEFORE_HOOK_FINISHED,
        updated_at=now,
    )
    if any(job.kind == HookJobKind.INSTALL for job in open_jobs):
        grant.last_hook_error = SUSPENDED_BEFORE_HOOK_FINISHED


def _revoke_keys(grant: PluginGrant, now) -> None:
    """Revoke every key of the grant's service account that is not revoked yet, superseded
    keys still inside their overlap included; the account is locked first (see the module's
    lock order)."""
    list(PluginServiceAccount.objects.select_for_update().filter(grant=grant).values_list("pk"))
    PluginServiceAccountKey.objects.filter(
        service_account__grant=grant, revoked_at__isnull=True
    ).update(revoked_at=now)
