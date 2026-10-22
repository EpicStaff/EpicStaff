"""Upgrade hooks: bringing each organization to the plugin's new version.

A grant's upgrade job is created only by `UpgradeHookService.ensure_job`, which `settle_grant`
calls when the grant's installed version is behind the current one and the current package
declares the hook. The job runs on the current version once the plugin is running; how it is
listed, claimed and retried after a failure is `HookJobService`'s (`UpgradeRules`). Until it
succeeds the grant is `upgrading`: its service account holds keys, and its people and runs
wait. After the automatic retries it is `upgrade_failed`, until a SuperAdmin retries it.

Lock order: the grant, then its jobs.
"""

from datetime import datetime

from django.utils import timezone

from plugins.activity.recorder import ActivityRecorder
from plugins.lifecycle.hook_timeouts import hook_timeout_seconds
from plugins.models import GrantState, HookJobKind, HookJobState, PluginGrant, PluginHookJob
from plugins.models.hook_job import OPEN_HOOK_JOB_STATES


class UpgradeHookService:
    def ensure_job(self, grant: PluginGrant) -> PluginHookJob:
        """Return the grant's open upgrade job, creating a pending one for the current package
        when it has none; the grant is locked and comes with its plugin and organization."""
        job = self.open_job(grant)
        if job is not None:
            return job
        package = grant.plugin.current_package
        return PluginHookJob.objects.create(
            plugin_id=grant.plugin_id,
            grant=grant,
            organization_id=grant.org_id,
            organization_name=grant.org.name,
            kind=HookJobKind.UPGRADE,
            package=package,
            timeout_seconds=hook_timeout_seconds(package.parsed_manifest, HookJobKind.UPGRADE),
        )

    @staticmethod
    def open_job(grant: PluginGrant) -> PluginHookJob | None:
        """The grant's pending or running upgrade job, locked."""
        return (
            grant.hook_jobs.select_for_update()
            .filter(kind=HookJobKind.UPGRADE, state__in=OPEN_HOOK_JOB_STATES)
            .first()
        )

    def restart_series(self, grant: PluginGrant, now: datetime) -> None:
        """Give the grant's pending upgrade job a fresh start: no failures counted, due now.

        For a new version: an organization whose hook was failing on the previous version
        gets every automatic retry again on this one.
        """
        PluginHookJob.objects.filter(
            grant=grant, kind=HookJobKind.UPGRADE, state=HookJobState.PENDING
        ).update(failures_in_series=0, next_attempt_at=None, updated_at=now)

    def retry_locked(self, grant: PluginGrant, actor) -> None:
        """Run an `upgrade_failed` grant's upgrade hook again; the caller locked the grant and
        checked the action.

        The latest upgrade job goes back to pending with a fresh series of automatic retries,
        or a new one is created when there is none; the grant is `upgrading`.
        """
        now = timezone.now()
        job = (
            grant.hook_jobs.select_for_update()
            .filter(kind=HookJobKind.UPGRADE)
            .order_by("-created_at", "-pk")
            .first()
        )
        if job is None or job.state not in (HookJobState.FAILED, *OPEN_HOOK_JOB_STATES):
            job = self.ensure_job(grant)
        elif job.state == HookJobState.FAILED:
            job.state = HookJobState.PENDING
            job.failures_in_series = 0
            job.next_attempt_at = None
            job.claimed_at = None
            job.deadline_at = None
            job.finished_at = None
            job.error = None
            job.save(
                update_fields=[
                    "state",
                    "failures_in_series",
                    "next_attempt_at",
                    "claimed_at",
                    "deadline_at",
                    "finished_at",
                    "error",
                    "updated_at",
                ]
            )
        grant.state = GrantState.UPGRADING
        grant.updated_at = now
        grant.save(update_fields=["state", "updated_at"])
        ActivityRecorder().upgrade_hook_retried(actor, job, grant.plugin.identifier)
