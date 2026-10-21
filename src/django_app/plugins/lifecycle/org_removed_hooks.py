"""Organization removed hooks: asking a plugin to delete its own data for an organization.

A job is created when an organization's plugin data must go: when its grant's data is
deleted (after the grace period, by a SuperAdmin, or because the plugin is deleted) and when
the organization itself is deleted. `OrgRemovedHookService.ensure_job` is the only place that
creates one; adding a reason an organization's plugin data must go means calling it, never
creating the row. The job keeps the organization's id and name, so it runs after the
organization is gone. How it runs and is retried is `HookJobService`'s (`OrgRemovedRules`).

A SuperAdmin may retry a job that waits for its next attempt or failed for good, and skip one
that has not run to the end. Skipping leaves the plugin's data for that organization where
the plugin keeps it until the plugin is deleted.
"""

from datetime import datetime
from enum import StrEnum

from django.db import IntegrityError, transaction
from django.db.models import Exists, OuterRef, QuerySet
from django.utils import timezone
from rbac.models import Organization

from plugins.activity.recorder import ActivityRecorder
from plugins.audit import log_org_removed_hook_action
from plugins.exceptions import (
    HookJobNotFoundError,
    OrgRemovedHookNotRetryableError,
    OrgRemovedHookNotSkippableError,
)
from plugins.lifecycle.hook_job_service import hook_timeout_seconds
from plugins.lifecycle.lifecycle_locks import lock_existing_plugin
from plugins.models import HookJobKind, HookJobState, Plugin, PluginGrant, PluginHookJob
from plugins.models.hook_job import ONE_OPEN_ORG_REMOVED_JOB_CONSTRAINT

# Jobs that still stand for the organization's data: waiting, running, or failed for good. A
# new reason to delete the data reuses one of them instead of creating a second.
UNFINISHED_ORG_REMOVED_STATES = (HookJobState.PENDING, HookJobState.RUNNING, HookJobState.FAILED)
# Finished as far as deleting a grant is concerned.
SETTLED_ORG_REMOVED_STATES = (HookJobState.SUCCEEDED, HookJobState.SKIPPED)


class OrgRemovedJobAction(StrEnum):
    RETRY = "retry"
    SKIP = "skip"


def allowed_org_removed_job_actions(job: PluginHookJob, now: datetime) -> list[OrgRemovedJobAction]:
    """What a SuperAdmin may do with an organization removed job now.

    A job waiting out a retry delay can be retried at once or skipped; one that is due can
    only be skipped (the node claims it next); one that failed for good can be retried or
    skipped. A running or finished job allows nothing.
    """
    if job.state == HookJobState.FAILED:
        return [OrgRemovedJobAction.RETRY, OrgRemovedJobAction.SKIP]
    if job.state != HookJobState.PENDING:
        return []
    if job.next_attempt_at is not None and job.next_attempt_at > now:
        return [OrgRemovedJobAction.RETRY, OrgRemovedJobAction.SKIP]
    return [OrgRemovedJobAction.SKIP]


def has_org_removed_hook(plugin: Plugin) -> bool:
    """Whether the plugin's current package has a backend that declares the hook."""
    package = plugin.current_package
    if package is None:
        return False
    manifest = package.parsed_manifest
    return manifest.backend is not None and manifest.hooks.org_removed


def latest_org_removed_job(plugin_id: int, organization_id: int) -> PluginHookJob | None:
    """The newest organization removed job of the plugin for the organization."""
    return (
        PluginHookJob.objects.filter(
            plugin_id=plugin_id, organization_id=organization_id, kind=HookJobKind.ORG_REMOVED
        )
        .order_by("-created_at", "-pk")
        .first()
    )


def org_removed_jobs(plugin: Plugin) -> QuerySet[PluginHookJob]:
    """The plugin's organization removed jobs, newest first, each annotated with
    `organization_exists`."""
    return (
        PluginHookJob.objects.filter(plugin=plugin, kind=HookJobKind.ORG_REMOVED)
        .annotate(
            organization_exists=Exists(Organization.objects.filter(pk=OuterRef("organization_id")))
        )
        .order_by("-created_at", "-pk")
    )


class OrgRemovedHookService:
    def ensure_job(
        self,
        plugin: Plugin,
        *,
        organization_id: int,
        organization_name: str,
        grant: PluginGrant | None,
    ) -> PluginHookJob | None:
        """The job asking `plugin` to delete its data for the organization, created if needed.

        None when the plugin's current package has no backend or does not declare the hook.
        An unfinished job of the plugin for the organization (pending, running or failed) is
        returned as it is; otherwise a new pending job is created for `grant` (None once the
        grant is gone), with the organization's name as it is now. Runs inside the caller's
        transaction, which holds the plugin's or the organization's lock.
        """
        if not has_org_removed_hook(plugin):
            return None
        existing = self._unfinished_job(plugin, organization_id)
        if existing is not None:
            return existing
        package = plugin.current_package
        try:
            # A savepoint: a create that loses a race with another one must not end the
            # caller's transaction.
            with transaction.atomic():
                return PluginHookJob.objects.create(
                    plugin=plugin,
                    grant=grant,
                    organization_id=organization_id,
                    organization_name=organization_name,
                    kind=HookJobKind.ORG_REMOVED,
                    package=package,
                    timeout_seconds=hook_timeout_seconds(
                        package.parsed_manifest, HookJobKind.ORG_REMOVED
                    ),
                )
        except IntegrityError as error:
            if _violated_constraint(error) != ONE_OPEN_ORG_REMOVED_JOB_CONSTRAINT:
                raise
            return self._unfinished_job(plugin, organization_id)

    def retry(self, identifier: str, job_id: int, actor) -> PluginHookJob:
        """Put an organization removed job back to pending, due now, with a new retry window
        from its next attempt; its last error stays until then.

        Raises:
            PluginNotFoundError: No such plugin.
            HookJobNotFoundError: No organization removed job `job_id` of this plugin.
            OrgRemovedHookNotRetryableError: The job is running, due, or finished.
        """
        now = timezone.now()
        with transaction.atomic():
            plugin, job = _locked_job(identifier, job_id)
            if OrgRemovedJobAction.RETRY not in allowed_org_removed_job_actions(job, now):
                raise OrgRemovedHookNotRetryableError()
            job.state = HookJobState.PENDING
            job.next_attempt_at = None
            job.first_attempt_at = None
            job.claimed_at = None
            job.deadline_at = None
            job.finished_at = None
            job.save(
                update_fields=[
                    "state",
                    "next_attempt_at",
                    "first_attempt_at",
                    "claimed_at",
                    "deadline_at",
                    "finished_at",
                    "updated_at",
                ]
            )
            ActivityRecorder().org_removed_hook_retried(actor, job, plugin.identifier)
            _log_on_commit("retried", actor, plugin.identifier, job)
        return job

    def skip(self, identifier: str, job_id: int, actor) -> PluginHookJob:
        """Give up on an organization removed job that has not run to the end.

        Raises:
            PluginNotFoundError: No such plugin.
            HookJobNotFoundError: No organization removed job `job_id` of this plugin.
            OrgRemovedHookNotSkippableError: The job is running or finished.
        """
        now = timezone.now()
        with transaction.atomic():
            plugin, job = _locked_job(identifier, job_id)
            if OrgRemovedJobAction.SKIP not in allowed_org_removed_job_actions(job, now):
                raise OrgRemovedHookNotSkippableError()
            self._skip_locked(job, plugin.identifier, actor=actor, now=now)
        return job

    def skip_failed(self, plugin: Plugin, now: datetime) -> int:
        """Skip, as the platform, every organization removed job of `plugin` that failed for
        good; the caller holds the plugin's lock. Returns how many."""
        failed = list(
            PluginHookJob.objects.select_for_update()
            .filter(plugin=plugin, kind=HookJobKind.ORG_REMOVED, state=HookJobState.FAILED)
            .order_by("pk")
        )
        for job in failed:
            self._skip_locked(job, plugin.identifier, actor=None, now=now)
        return len(failed)

    @staticmethod
    def _skip_locked(job: PluginHookJob, identifier: str, *, actor, now: datetime) -> None:
        state_before = job.state
        job.state = HookJobState.SKIPPED
        job.finished_at = now
        job.save(update_fields=["state", "finished_at", "updated_at"])
        ActivityRecorder().org_removed_hook_skipped(actor, job, identifier, state_before)
        _log_on_commit("skipped", actor, identifier, job)

    @staticmethod
    def _unfinished_job(plugin: Plugin, organization_id: int) -> PluginHookJob | None:
        return (
            PluginHookJob.objects.filter(
                plugin=plugin,
                organization_id=organization_id,
                kind=HookJobKind.ORG_REMOVED,
                state__in=UNFINISHED_ORG_REMOVED_STATES,
            )
            .order_by("-created_at", "-pk")
            .first()
        )


def _locked_job(identifier: str, job_id: int) -> tuple[Plugin, PluginHookJob]:
    """Lock the plugin, the job's grant when it has one, then the job."""
    plugin = lock_existing_plugin(identifier)
    jobs = PluginHookJob.objects.filter(pk=job_id, plugin=plugin, kind=HookJobKind.ORG_REMOVED)
    grant_id = jobs.values_list("grant_id", flat=True).first()
    if grant_id is not None:
        PluginGrant.objects.select_for_update().filter(pk=grant_id).only("pk").first()
    job = jobs.select_for_update().first()
    if job is None:
        raise HookJobNotFoundError()
    return plugin, job


def _log_on_commit(action: str, actor, identifier: str, job: PluginHookJob) -> None:
    job_id = job.pk
    organization_id = job.organization_id

    def log_action() -> None:
        log_org_removed_hook_action(
            action, actor, identifier=identifier, job_id=job_id, org_id=organization_id
        )

    transaction.on_commit(log_action)


def _violated_constraint(error: IntegrityError) -> str | None:
    diagnostics = getattr(error.__cause__, "diag", None)
    return getattr(diagnostics, "constraint_name", None)
