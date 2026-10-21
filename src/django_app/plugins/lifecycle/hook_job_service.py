"""Lifecycle hooks: the jobs EpicStaff wants a plugin's backend to run, and their outcome.

A job is created `pending` by the lifecycle step that needs it (a grant, for `install`). The
node lists it in its desired state and claims it once the plugin's process is ready; the
claim signs the call (an assertion bound to the exact body) and the node makes it at once,
then posts the result. The result moves the grant on. A `running` job whose node never
reports a result fails two minutes after its deadline.

Adding a hook kind: `HookKind` and `HOOK_PATHS` in the SDK's hook API, a `HookJobKind`
choice and its migration, its `HOOK_KIND_RULES` entry (the grant states it runs in and
leads to), the lifecycle step that creates the job, and its activity actions.
"""

import operator
import secrets
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta
from functools import reduce

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from epicstaff_plugin.contracts.gateway_context import ContextOrganization, PluginIdentity
from epicstaff_plugin.contracts.hook_api import (
    HOOK_ASSERTION_GRACE_SECONDS,
    HookAssertionClaims,
    HookRequest,
    encode_hook_assertion,
    encode_hook_body,
    hook_body_sha256,
)
from epicstaff_plugin.contracts.manifest import MAX_HOOK_TIMEOUT_SECONDS, PluginManifest
from epicstaff_plugin.problems import Problem, format_loc
from pydantic import ValidationError
from src.shared.models.plugin_nodes import DesiredHookJob, HookInvocation, HookResult

from plugins.activity.recorder import ActivityRecorder
from plugins.audit import log_hook_claimed, log_hook_finished
from plugins.exceptions import (
    GrantNotFoundError,
    HookJobNotClaimableError,
    HookJobNotFoundError,
    HookJobNotRunningError,
    HookNotRetryableError,
    InvalidHookResultError,
)
from plugins.identity.signing_keys import cached_signing_key
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
class HookKindRules:
    """The grant states around a job of one kind.

    The job is listed and claimable only while its grant is in `runs_in`; its result moves
    the grant from there to `succeeded` or `failed`.
    """

    runs_in: str
    succeeded: str
    failed: str


HOOK_KIND_RULES = {
    HookJobKind.INSTALL: HookKindRules(
        runs_in=GrantState.GRANTING, succeeded=GrantState.ACTIVE, failed=GrantState.INSTALL_FAILED
    ),
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
            kind=HookJobKind.INSTALL,
            package=package,
            timeout_seconds=hook_timeout_seconds(package.parsed_manifest, HookJobKind.INSTALL),
        )

    def pending_jobs_by_plugin(self, plugin_ids: list[int]) -> dict[int, list[DesiredHookJob]]:
        """The jobs each plugin's node should run, oldest first, in one query.

        A job is listed while it is pending and its grant still exists in the state the
        job's kind runs in.
        """
        jobs = defaultdict(list)
        if not plugin_ids:
            return jobs
        rows = (
            PluginHookJob.objects.filter(
                _runnable_q(), plugin_id__in=plugin_ids, state=HookJobState.PENDING
            )
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
            HookJobNotClaimableError: The job is not pending, its plugin is not running, or
                its grant is gone or not in the state the job runs in.
        """
        self.fail_overdue(node)
        now = timezone.now()
        with transaction.atomic():
            job = self._job_of_node(node, job_id, lock=True)
            grant = job.grant
            plugin = job.plugin
            if (
                job.state != HookJobState.PENDING
                or plugin.state != PluginState.RUNNING
                or plugin.current_package is None
                or grant is None
                or grant.state != HOOK_KIND_RULES[job.kind].runs_in
            ):
                raise HookJobNotClaimableError()
            job.state = HookJobState.RUNNING
            job.attempt += 1
            job.claimed_at = now
            job.deadline_at = now + timedelta(seconds=job.timeout_seconds)
            job.finished_at = None
            job.error = None
            job.save(
                update_fields=[
                    "state",
                    "attempt",
                    "claimed_at",
                    "deadline_at",
                    "finished_at",
                    "error",
                    "updated_at",
                ]
            )
            invocation = _invocation(job, plugin.identifier, plugin.current_package.version, grant)
        log_hook_claimed(
            identifier=plugin.identifier,
            job_id=job.pk,
            kind=job.kind,
            org_id=job.organization_id,
            attempt=job.attempt,
        )
        return invocation

    def record_result(self, node: PluginNode, job_id: int, result: HookResult) -> None:
        """Finish a running job with the node's result, and move its grant on.

        Raises:
            HookJobNotFoundError: No such job on a placement of this node.
            HookJobNotRunningError: The job is not running, or runs another attempt.
        """
        with transaction.atomic():
            job = self._job_of_node(node, job_id, lock=True)
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
        """
        with transaction.atomic():
            grant = (
                PluginGrant.objects.select_for_update(of=("self",))
                .select_related("plugin")
                .filter(pk=grant_id, plugin__identifier=identifier)
                .first()
            )
            if grant is None:
                raise GrantNotFoundError()
            job = (
                grant.hook_jobs.select_for_update()
                .filter(kind=HookJobKind.INSTALL, state=HookJobState.FAILED)
                .order_by("-created_at", "-pk")
                .first()
            )
            if grant.state != GrantState.INSTALL_FAILED or job is None:
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

    def fail_overdue(self, node: PluginNode) -> None:
        """Fail every running job of `node`'s whose result is overdue, as if it had failed."""
        overdue_ids = list(
            PluginHookJob.objects.filter(
                plugin__placement__node=node,
                state=HookJobState.RUNNING,
                deadline_at__lt=timezone.now() - RESULT_GRACE,
            ).values_list("pk", flat=True)
        )
        for job_id in overdue_ids:
            with transaction.atomic():
                job = (
                    PluginHookJob.objects.select_for_update(of=("self",))
                    .select_related("plugin", "grant")
                    .filter(pk=job_id, state=HookJobState.RUNNING)
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

    @staticmethod
    def _job_of_node(node: PluginNode, job_id: int, *, lock: bool) -> PluginHookJob:
        jobs = PluginHookJob.objects.select_related("plugin__current_package", "grant__org").defer(
            "plugin__current_package__icon_bytes"
        )
        if lock:
            jobs = jobs.select_for_update(of=("self",))
        job = jobs.filter(pk=job_id, plugin__placement__node=node).first()
        if job is None:
            raise HookJobNotFoundError()
        return job

    @staticmethod
    def _finish(job: PluginHookJob, *, succeeded: bool, error: str | None) -> None:
        job.state = HookJobState.SUCCEEDED if succeeded else HookJobState.FAILED
        job.finished_at = timezone.now()
        job.error = error
        job.save(update_fields=["state", "finished_at", "error", "updated_at"])
        _move_grant(job, succeeded=succeeded, error=error)
        ActivityRecorder().hook_finished(
            job, job.plugin.identifier, succeeded=succeeded, error=error
        )


def _move_grant(job: PluginHookJob, *, succeeded: bool, error: str | None) -> None:
    """Move the job's grant on, if it still exists and still waits for this job."""
    if job.grant_id is None:
        return
    rules = HOOK_KIND_RULES[job.kind]
    PluginGrant.objects.filter(pk=job.grant_id, state=rules.runs_in).update(
        state=rules.succeeded if succeeded else rules.failed,
        last_hook_error=None if succeeded else error,
        updated_at=timezone.now(),
    )


def _runnable_q() -> Q:
    """Jobs whose grant is in the state their kind runs in."""
    return reduce(
        operator.or_,
        (Q(kind=kind, grant__state=rules.runs_in) for kind, rules in HOOK_KIND_RULES.items()),
    )


def _invocation(
    job: PluginHookJob, identifier: str, version: str, grant: PluginGrant
) -> HookInvocation:
    body = encode_hook_body(
        HookRequest(
            format=1,
            job_id=job.pk,
            attempt=job.attempt,
            kind=job.kind,
            org=ContextOrganization(id=grant.org_id, name=grant.org.name),
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
