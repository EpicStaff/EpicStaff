"""Upgrade hooks: bringing each organization to the plugin's new version.

A grant's upgrade job is created only by `UpgradeHookService.ensure_job`, which `settle_grant`
calls when the grant's installed version is behind the current one and the current package
declares the hook. The job runs on the current version once the plugin is running; how it is
listed, claimed and retried after a failure is `HookJobService`'s (`UpgradeRules`). Until it
succeeds the grant is `upgrading`: its service account holds keys, and its people and runs
wait. After the automatic retries it is `upgrade_failed`, until a SuperAdmin retries it.

Lock order: the grant, then its jobs.

Settling every grant of a plugin at once (an upgrade's completion or cancel) runs inside
`UpgradeHookService.batch`, so the jobs `settle_grant` asks for cost a constant number of
queries, whatever the number of grants.
"""

from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime

from django.utils import timezone

from plugins.activity.recorder import ActivityRecorder
from plugins.lifecycle.hook_timeouts import hook_timeout_seconds
from plugins.models import GrantState, HookJobKind, HookJobState, PluginGrant, PluginHookJob
from plugins.models.hook_job import OPEN_HOOK_JOB_STATES


@dataclass
class UpgradeJobBatch:
    """The open upgrade jobs of a set of grants, read and locked at once, and the jobs
    `ensure_job` made for the others, created together when the batch ends; both by grant id."""

    grant_ids: frozenset[int]
    open_jobs: dict[int, PluginHookJob]
    created: dict[int, PluginHookJob] = field(default_factory=dict)

    def pending_job_ids(self, grants: Iterable[PluginGrant]) -> list[int]:
        """The ids of these grants' jobs that were pending before the batch; not those it made."""
        return [
            job.pk
            for grant in grants
            if (job := self.open_jobs.get(grant.pk)) is not None
            and job.state == HookJobState.PENDING
        ]


_current_batch: ContextVar[UpgradeJobBatch | None] = ContextVar("upgrade_job_batch", default=None)


class UpgradeHookService:
    def ensure_job(self, grant: PluginGrant) -> PluginHookJob:
        """Return the grant's open upgrade job, creating a pending one for the current package
        when it has none; the grant is locked and comes with its plugin and organization.

        Inside `batch`, a grant of the batch costs no query: its open job comes from the
        batch, and a new one is created when the batch ends.
        """
        current = _current_batch.get()
        if current is None or grant.pk not in current.grant_ids:
            job = self.open_job(grant)
            if job is None:
                job = self._new_job(grant)
                job.save()
            return job
        job = current.open_jobs.get(grant.pk) or current.created.get(grant.pk)
        if job is None:
            job = current.created[grant.pk] = self._new_job(grant)
        return job

    @contextmanager
    def batch(self, grants: list[PluginGrant]) -> Iterator[UpgradeJobBatch]:
        """Settle `grants` (locked, ascending pk) inside: their open upgrade jobs are read and
        locked in one query, and the jobs `ensure_job` makes are created in one more as the
        block ends without an error."""
        open_jobs = {}
        if grants:
            for job in (
                PluginHookJob.objects.select_for_update()
                .filter(grant__in=grants, kind=HookJobKind.UPGRADE, state__in=OPEN_HOOK_JOB_STATES)
                .order_by("pk")
            ):
                open_jobs[job.grant_id] = job
        batch = UpgradeJobBatch(frozenset(grant.pk for grant in grants), open_jobs)
        token = _current_batch.set(batch)
        try:
            yield batch
        finally:
            _current_batch.reset(token)
        if batch.created:
            PluginHookJob.objects.bulk_create(list(batch.created.values()))

    @staticmethod
    def _new_job(grant: PluginGrant) -> PluginHookJob:
        package = grant.plugin.current_package
        return PluginHookJob(
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

    def restart_series(self, job_ids: list[int], now: datetime) -> None:
        """Give these pending upgrade jobs a fresh start: no failures counted, due now; one
        query, none for no job.

        For a new version: an organization whose hook was failing on the previous version
        gets every automatic retry again on this one.
        """
        if not job_ids:
            return
        PluginHookJob.objects.filter(pk__in=job_ids, state=HookJobState.PENDING).update(
            failures_in_series=0, next_attempt_at=None, updated_at=now
        )

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
