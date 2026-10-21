"""Lifecycle hooks: the jobs EpicStaff wants a plugin's backend to run, and their outcome.

A job is created `pending` by the lifecycle step that needs it: a grant, for `install`;
deleting an organization's plugin data, for `org_removed` (`OrgRemovedHookService`). The node
lists it in its desired state and claims it once the plugin's process is ready; the claim
signs the call (an assertion bound to the exact body) and the node makes it at once, then
posts the result. A `running` job whose node never reports a result fails two minutes after
its deadline. A `pending` job never times out: it waits until the plugin's process is ready
to claim it.

What a result does depends on the kind (`HOOK_KIND_RULES`). An install job moves its grant
on, and a SuperAdmin retries a failed one. An organization removed job never moves a grant:
a failed attempt is retried on the SDK's schedule (`org_removed_retry_delay`) until the retry
window from its first attempt has passed, and only then does the job fail.

Lock order: whatever changes a job and may change its grant locks the grant first, then the
job, as suspension does (it fails the grant's open jobs), so the two never deadlock.

Adding a hook kind: `HookKind` and `HOOK_PATHS` in the SDK's hook API, a `HookJobKind`
choice and its migration, its `HOOK_KIND_RULES` entry (when its jobs are listed and
claimable, and what a result does), the lifecycle step that creates the job, and its activity
actions.
"""

import operator
import secrets
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import reduce

from django.db import transaction
from django.db.models import F, Q, QuerySet, Window
from django.db.models.functions import RowNumber
from django.utils import timezone
from epicstaff_plugin.contracts.gateway_context import ContextOrganization, PluginIdentity
from epicstaff_plugin.contracts.hook_api import (
    HOOK_ASSERTION_GRACE_SECONDS,
    ORG_REMOVED_RETRY_WINDOW_SECONDS,
    HookAssertionClaims,
    HookRequest,
    encode_hook_assertion,
    encode_hook_body,
    hook_body_sha256,
    org_removed_retry_delay,
)
from epicstaff_plugin.contracts.manifest import MAX_HOOK_TIMEOUT_SECONDS, PluginManifest
from epicstaff_plugin.problems import Problem, format_loc
from pydantic import ValidationError
from src.shared.models.plugin_nodes import (
    MAX_PENDING_HOOK_JOBS,
    DesiredHookJob,
    HookInvocation,
    HookResult,
)

from plugins.activity.recorder import ActivityRecorder
from plugins.audit import log_hook_claimed, log_hook_finished, log_hook_gave_up
from plugins.exceptions import (
    HookJobNotClaimableError,
    HookJobNotFoundError,
    HookJobNotRunningError,
    HookNotRetryableError,
    InvalidHookResultError,
)
from plugins.identity.signing_keys import cached_signing_key
from plugins.lifecycle.grant_actions import GrantAction, assert_grant_action
from plugins.lifecycle.lifecycle_locks import lock_grant
from plugins.models import (
    GrantState,
    HookJobKind,
    HookJobState,
    PluginGrant,
    PluginHookJob,
    PluginNode,
    PluginPackage,
    PluginState,
)
from plugins.origins import PluginOrigins


@dataclass(frozen=True)
class GrantStepRules:
    """A hook that is a step of its grant's lifecycle (install).

    Its jobs are listed and claimable only while the grant is in `runs_in` and the plugin is
    running; the result moves the grant from there to `succeeded` or `failed`. A failed job
    waits for a SuperAdmin to retry it.
    """

    kind: str
    runs_in: str
    succeeded: str
    failed: str

    def listed(self, now: datetime) -> Q:
        return Q(kind=self.kind, grant__state=self.runs_in)

    def claimable(self, job: PluginHookJob, now: datetime) -> bool:
        return (
            job.plugin.state == PluginState.RUNNING
            and job.grant is not None
            and job.grant.state == self.runs_in
        )

    def organization_name(self, job: PluginHookJob) -> str:
        return job.grant.org.name

    def finish(self, job: PluginHookJob, *, succeeded: bool, error: str | None, now) -> None:
        _close(job, HookJobState.SUCCEEDED if succeeded else HookJobState.FAILED, error, now)
        PluginGrant.objects.filter(pk=job.grant_id, state=self.runs_in).update(
            state=self.succeeded if succeeded else self.failed,
            last_hook_error=None if succeeded else error,
            updated_at=now,
        )
        ActivityRecorder().hook_finished(
            job, job.plugin.identifier, succeeded=succeeded, error=error
        )


# The plugin states in which an organization removed hook may run: the process is started for
# it while the plugin is uninstalled or being deleted (`DesiredStateBuilder`).
ORG_REMOVED_PLUGIN_STATES = (PluginState.RUNNING, PluginState.UNINSTALLING, PluginState.PURGING)


@dataclass(frozen=True)
class OrgRemovedRules:
    """The hook that deletes a plugin's own data for an organization that is leaving.

    Its job runs once due (`next_attempt_at`), while the plugin is running, uninstalled or
    being deleted, and while its grant is gone (the organization was deleted) or being
    purged. Its body names the organization as it was when the job was created. A result
    never moves the grant. A failed attempt goes back to `pending` for the next attempt of the
    SDK's retry schedule; once `ORG_REMOVED_RETRY_WINDOW_SECONDS` have passed since the first
    attempt it fails for good, until a SuperAdmin retries or skips it.
    """

    kind: str = HookJobKind.ORG_REMOVED

    def listed(self, now: datetime) -> Q:
        return (
            Q(kind=self.kind, plugin__state__in=ORG_REMOVED_PLUGIN_STATES)
            & (Q(grant__isnull=True) | Q(grant__state=GrantState.PURGING))
            & (Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=now))
        )

    def claimable(self, job: PluginHookJob, now: datetime) -> bool:
        return (
            job.plugin.state in ORG_REMOVED_PLUGIN_STATES
            and (job.grant is None or job.grant.state == GrantState.PURGING)
            and (job.next_attempt_at is None or job.next_attempt_at <= now)
        )

    def organization_name(self, job: PluginHookJob) -> str:
        return job.organization_name

    def finish(self, job: PluginHookJob, *, succeeded: bool, error: str | None, now) -> None:
        identifier = job.plugin.identifier
        if succeeded:
            _close(job, HookJobState.SUCCEEDED, None, now)
            ActivityRecorder().hook_finished(job, identifier, succeeded=True, error=None)
            return
        if now < retry_until(job):
            job.state = HookJobState.PENDING
            job.next_attempt_at = now + timedelta(seconds=org_removed_retry_delay(job.attempt))
            job.error = error
            job.save(update_fields=["state", "next_attempt_at", "error", "updated_at"])
            return
        _close(job, HookJobState.FAILED, error, now)
        ActivityRecorder().hook_finished(job, identifier, succeeded=False, error=error)
        log_hook_gave_up(
            identifier=identifier,
            job_id=job.pk,
            org_id=job.organization_id,
            attempts=job.attempt,
        )


def retry_until(job: PluginHookJob) -> datetime | None:
    """When an organization removed job stops being retried by itself: its retry window from
    the first attempt; None before the first attempt."""
    if job.first_attempt_at is None:
        return None
    return job.first_attempt_at + timedelta(seconds=ORG_REMOVED_RETRY_WINDOW_SECONDS)


HOOK_KIND_RULES = {
    HookJobKind.INSTALL: GrantStepRules(
        kind=HookJobKind.INSTALL,
        runs_in=GrantState.GRANTING,
        succeeded=GrantState.ACTIVE,
        failed=GrantState.INSTALL_FAILED,
    ),
    HookJobKind.ORG_REMOVED: OrgRemovedRules(),
}
# How long after its deadline a running job waits for the node's result before it fails.
RESULT_GRACE = timedelta(seconds=120)
NO_RESULT_IN_TIME = "The plugin node reported no result in time"
HOOK_FAILED_WITHOUT_REASON = "The plugin hook failed"
RESULT_LOC = "result"


def hook_timeout_seconds(manifest: PluginManifest, kind: str) -> int:
    """The manifest's timeout for a hook kind, else the platform maximum for it."""
    timeouts = manifest.hooks.timeouts_seconds
    declared = getattr(timeouts, kind, None) if timeouts is not None else None
    return declared or MAX_HOOK_TIMEOUT_SECONDS[kind]


def parse_hook_result(raw: bytes) -> HookResult:
    """Parse a node's hook result, ignoring fields this EpicStaff does not know.

    Raises:
        InvalidHookResultError: The body is not a valid result; problems located under `result`.
    """
    try:
        return HookResult.model_validate_json(raw, extra="ignore")
    except ValidationError as error:
        raise InvalidHookResultError(
            Problem(format_loc(RESULT_LOC, detail["loc"]), detail["msg"])
            for detail in error.errors(include_url=False)
        ) from None


class HookJobService:
    def create_install_job(self, grant: PluginGrant, package: PluginPackage) -> PluginHookJob:
        """Create the pending install job of a grant; run inside the grant's transaction."""
        return PluginHookJob.objects.create(
            plugin_id=grant.plugin_id,
            grant=grant,
            organization_id=grant.org_id,
            organization_name=grant.org.name,
            kind=HookJobKind.INSTALL,
            package=package,
            timeout_seconds=hook_timeout_seconds(package.parsed_manifest, HookJobKind.INSTALL),
        )

    def pending_jobs_by_plugin(
        self, plugin_ids: list[int], now: datetime | None = None
    ) -> dict[int, list[DesiredHookJob]]:
        """The jobs each plugin's node should run, oldest first, in one query.

        A job is listed while it is pending and its kind's rules list it now
        (`HOOK_KIND_RULES`): an install job while its grant is being granted, an organization
        removed job once due. At most the oldest `MAX_PENDING_HOOK_JOBS` of a plugin are
        listed, as many as a desired placement carries; the next ones are listed as these
        finish.
        """
        jobs = defaultdict(list)
        if not plugin_ids:
            return jobs
        rows = (
            PluginHookJob.objects.filter(
                _listed_q(now or timezone.now()),
                plugin_id__in=plugin_ids,
                state=HookJobState.PENDING,
            )
            .annotate(
                position=Window(
                    RowNumber(),
                    partition_by=[F("plugin_id")],
                    order_by=[F("created_at").asc(), F("pk").asc()],
                )
            )
            .filter(position__lte=MAX_PENDING_HOOK_JOBS)
            .order_by("created_at", "pk")
            .values_list("plugin_id", "pk", "kind", "organization_id")
        )
        for plugin_id, job_id, kind, organization_id in rows:
            jobs[plugin_id].append(
                DesiredHookJob(job_id=job_id, kind=kind, organization_id=organization_id)
            )
        return jobs

    def claim(self, node: PluginNode, job_id: int) -> HookInvocation:
        """Start the next attempt of a job of `node`'s and hand back the call to make.

        The assertion is signed now and expires the job's timeout plus a minute from now,
        so the node makes the call at once.

        Raises:
            HookJobNotFoundError: No such job on a placement of this node.
            HookJobNotClaimableError: The job is not pending, or its kind's rules do not let
                it run now: an install job's plugin is not running or its grant is gone or
                has moved on; an organization removed job is not due yet, its plugin is not
                running, uninstalled or being deleted, or its grant is neither gone nor being
                purged.
        """
        self.fail_overdue(node)
        now = timezone.now()
        with transaction.atomic():
            job = self._lock_job_of_node(node, job_id)
            plugin = job.plugin
            rules = HOOK_KIND_RULES[job.kind]
            if (
                job.state != HookJobState.PENDING
                or plugin.current_package is None
                or not rules.claimable(job, now)
            ):
                raise HookJobNotClaimableError()
            job.state = HookJobState.RUNNING
            job.attempt += 1
            job.claimed_at = now
            if job.first_attempt_at is None:
                job.first_attempt_at = now
            job.next_attempt_at = None
            job.deadline_at = now + timedelta(seconds=job.timeout_seconds)
            job.finished_at = None
            job.error = None
            job.save(
                update_fields=[
                    "state",
                    "attempt",
                    "claimed_at",
                    "first_attempt_at",
                    "next_attempt_at",
                    "deadline_at",
                    "finished_at",
                    "error",
                    "updated_at",
                ]
            )
            invocation = _invocation(
                job, plugin.identifier, plugin.current_package.version, rules.organization_name(job)
            )
        log_hook_claimed(
            identifier=plugin.identifier,
            job_id=job.pk,
            kind=job.kind,
            org_id=job.organization_id,
            attempt=job.attempt,
        )
        return invocation

    def record_result(self, node: PluginNode, job_id: int, result: HookResult) -> None:
        """Finish a running job's attempt with the node's result, by its kind's rules.

        Raises:
            HookJobNotFoundError: No such job on a placement of this node.
            HookJobNotRunningError: The job is not running, or runs another attempt.
        """
        with transaction.atomic():
            job = self._lock_job_of_node(node, job_id)
            if job.state != HookJobState.RUNNING or job.attempt != result.attempt:
                raise HookJobNotRunningError()
            succeeded = result.outcome == "succeeded"
            error = None if succeeded else (result.error or HOOK_FAILED_WITHOUT_REASON)
            self._finish(job, succeeded=succeeded, error=error)
        log_hook_finished(
            identifier=job.plugin.identifier,
            job_id=job.pk,
            kind=job.kind,
            org_id=job.organization_id,
            attempt=job.attempt,
            outcome=result.outcome,
            duration_ms=result.duration_ms,
        )

    def retry(self, identifier: str, grant_id: int, actor) -> PluginGrant:
        """Put a grant's failed install job back to pending; the grant is `granting` again.

        Raises:
            GrantNotFoundError: No such grant of this plugin.
            HookNotRetryableError: The grant's install hook has not failed.
            PluginUninstallingError: The plugin is uninstalled or being deleted.
        """
        with transaction.atomic():
            grant = lock_grant(identifier, grant_id)
            assert_grant_action(grant, GrantAction.RETRY_INSTALL)
            job = (
                grant.hook_jobs.select_for_update()
                .filter(kind=HookJobKind.INSTALL, state=HookJobState.FAILED)
                .order_by("-created_at", "-pk")
                .first()
            )
            if job is None:
                raise HookNotRetryableError()
            job.state = HookJobState.PENDING
            job.claimed_at = None
            job.deadline_at = None
            job.finished_at = None
            job.error = None
            job.save(
                update_fields=[
                    "state",
                    "claimed_at",
                    "deadline_at",
                    "finished_at",
                    "error",
                    "updated_at",
                ]
            )
            grant.state = GrantState.GRANTING
            grant.save(update_fields=["state", "updated_at"])
            ActivityRecorder().install_hook_retried(actor, job, grant.plugin.identifier)
        return grant

    def fail_overdue(self, node: PluginNode | None = None) -> int:
        """End the attempt of every running job whose result is overdue, as if it had failed.

        Only `node`'s jobs, or every node's when None (the scheduled sweep, so a job of a node
        that stopped reporting ends too). Each job is then what its kind's rules make of a
        failed attempt. Returns how many there were.
        """
        overdue = PluginHookJob.objects.filter(
            state=HookJobState.RUNNING, deadline_at__lt=timezone.now() - RESULT_GRACE
        )
        if node is not None:
            overdue = overdue.filter(plugin__placement__node=node)
        overdue_ids = list(overdue.order_by("pk").values_list("pk", flat=True))
        for job_id in overdue_ids:
            with transaction.atomic():
                running = PluginHookJob.objects.filter(pk=job_id, state=HookJobState.RUNNING)
                self._lock_grant_of(running)
                job = (
                    running.select_for_update(of=("self",))
                    .select_related("plugin", "grant")
                    .first()
                )
                if job is None:
                    continue
                self._finish(job, succeeded=False, error=NO_RESULT_IN_TIME)
            log_hook_finished(
                identifier=job.plugin.identifier,
                job_id=job.pk,
                kind=job.kind,
                org_id=job.organization_id,
                attempt=job.attempt,
                outcome="failed",
                duration_ms=None,
            )
        return len(overdue_ids)

    @classmethod
    def _lock_job_of_node(cls, node: PluginNode, job_id: int) -> PluginHookJob:
        """Lock a job of `node`'s and its grant, the grant first; run inside a transaction."""
        of_node = PluginHookJob.objects.filter(pk=job_id, plugin__placement__node=node)
        cls._lock_grant_of(of_node)
        job = (
            of_node.select_for_update(of=("self",))
            .select_related("plugin__current_package", "grant__org")
            .defer("plugin__current_package__icon_bytes")
            .first()
        )
        if job is None:
            raise HookJobNotFoundError()
        return job

    @staticmethod
    def _lock_grant_of(job: QuerySet) -> None:
        """Lock the grant of the job `job` matches, when it matches one that has a grant."""
        grant_id = job.values_list("grant_id", flat=True).first()
        if grant_id is not None:
            PluginGrant.objects.select_for_update().filter(pk=grant_id).only("pk").first()

    @staticmethod
    def _finish(job: PluginHookJob, *, succeeded: bool, error: str | None) -> None:
        HOOK_KIND_RULES[job.kind].finish(job, succeeded=succeeded, error=error, now=timezone.now())


def _close(job: PluginHookJob, state: str, error: str | None, now: datetime) -> None:
    job.state = state
    job.finished_at = now
    job.error = error
    job.save(update_fields=["state", "finished_at", "error", "updated_at"])


def _listed_q(now: datetime) -> Q:
    """Jobs their kind's rules list now."""
    return reduce(operator.or_, (rules.listed(now) for rules in HOOK_KIND_RULES.values()))


def _invocation(
    job: PluginHookJob, identifier: str, version: str, organization_name: str
) -> HookInvocation:
    body = encode_hook_body(
        HookRequest(
            format=1,
            job_id=job.pk,
            attempt=job.attempt,
            kind=job.kind,
            org=ContextOrganization(id=job.organization_id, name=organization_name),
            plugin=PluginIdentity(identifier=identifier, version=version),
            previous_version=None,
        )
    )
    issued_at = int(time.time())
    key = cached_signing_key.get()
    assertion = encode_hook_assertion(
        HookAssertionClaims(
            iss=PluginOrigins().epicstaff_origin,
            aud=identifier,
            iat=issued_at,
            exp=issued_at + job.timeout_seconds + HOOK_ASSERTION_GRACE_SECONDS,
            jti=secrets.token_hex(16),
            kind=job.kind,
            job_id=job.pk,
            attempt=job.attempt,
            org_id=job.organization_id,
            body_sha256=hook_body_sha256(body),
        ),
        key.private_key,
        key.kid,
    )
    return HookInvocation(
        job_id=job.pk,
        kind=job.kind,
        attempt=job.attempt,
        organization_id=job.organization_id,
        timeout_seconds=job.timeout_seconds,
        assertion=assertion,
        body=body.decode("utf-8"),
    )
