"""Run a placement's lifecycle hooks (the desired placement's `hook_jobs`), apart from converge.

One `HookRunner` per placement takes the oldest listed job once the plugin is ready for it:

- the desired state wants the process running, it runs, and its last health check passed;
- the runtime file the node last wrote has the credentials revision the desired state names;
- for an install job, that runtime file lists the job's organization in `service_accounts`, so
  the plugin holds the service-account key the hook's work needs. An `org_removed` job does not
  wait for one: the organization's data is being deleted, and it has no key any more.

A desired placement whose upgrade is in `maintenance` or `migrating` lists no hook jobs (the node
contract refuses one that does), so nothing is claimed then; `drain` waits for the call in
flight, so the node can stop the plugin for an upgrade without cutting a hook short.

Until then the job waits; the runner looks again whenever the desired placement, the runtime
file or the process's state changes. When it is ready, the runner claims the job from
django_app, which answers with an assertion signed for this one call and bound to its body,
makes the call at once (`PluginHookCaller`), and posts the result, retrying a result that cannot
be delivered for up to 120 s. A job that cannot be claimed (django_app answers 404 or 409) is
skipped: an earlier claim took it, or it is gone.

One hook at a time per placement; each placement's runner is a task of its own, so placements
run their hooks in parallel and converge and reports go on during a hook. If the process
restarts during the call, the result is failed with "the plugin restarted during the hook"; if
it is stopped (the desired state no longer wants it running, or the placement goes), with "the
plugin stopped during the hook". A SuperAdmin retries the job. A job just tried is not claimed again for 30 s while the desired
state still lists it: the node's copy of the desired state may predate the claim.

Neither the assertion, the body nor the runtime file is ever logged.
"""

import asyncio
import contextlib
import math
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace

from epicstaff_plugin.contracts.hook_api import KEYLESS_HOOK_KINDS
from loguru import logger
from src.shared.models.plugin_nodes import (
    DesiredHookJob,
    DesiredPlacement,
    HookInvocation,
    HookResult,
)

from es_plugins.agent.django_client import DjangoNodeClient, NodeApiError
from es_plugins.hooks.hook_caller import HookOutcome, PluginHookCaller
from es_plugins.supervisor.process_supervisor import ProcessSupervisor

RECLAIM_AFTER_SECONDS = 30.0
RESULT_DELIVERY_SECONDS = 120.0
RESULT_FIRST_RETRY_SECONDS = 1.0
RESULT_LONGEST_RETRY_SECONDS = 15.0
# A runner closed during a call (the placement goes, or the node stops) reports it once, this
# briefly: the node's shutdown must stay within its container's stop timeout.
STOPPED_RESULT_SECONDS = 2.0
RESTARTED_DURING_HOOK = "the plugin restarted during the hook"
STOPPED_DURING_HOOK = "the plugin stopped during the hook"
# How much longer than a call's own timeout a drain waits for it.
DRAIN_MARGIN_SECONDS = 60.0
# Longer than a claim request may take (django_client's timeout).
CLAIM_SECONDS = 40.0


@dataclass(frozen=True)
class WrittenRuntimeFile:
    """What hooks need to know of the runtime file the node last wrote for a placement."""

    credentials_revision: str
    organization_ids: frozenset[int]
    """The organizations its `service_accounts` lists."""


class HookRunner:
    def __init__(
        self,
        placement: DesiredPlacement,
        supervisor: ProcessSupervisor,
        django: DjangoNodeClient,
        caller: PluginHookCaller,
    ):
        self._placement = placement
        self._supervisor = supervisor
        self._django = django
        self._caller = caller
        self._written: WrittenRuntimeFile | None = None
        # job id -> monotonic time of its last claim, for the jobs the desired state still lists.
        self._tried_at: dict[int, float] = {}
        self._changed = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._idle = asyncio.Event()
        self._idle.set()
        # Monotonic time by which the call in flight must be over.
        self._call_deadline: float | None = None

    def start(self) -> None:
        self._changed.set()
        self._task = asyncio.create_task(self._loop(), name=f"hooks-{self._placement.placement_id}")

    async def close(self) -> None:
        """Stop the runner; a hook call in progress is reported failed, briefly and once."""
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

    def update(self, placement: DesiredPlacement) -> None:
        listed = {job.job_id for job in placement.hook_jobs}
        # A job that left the list and is back (its hook failed, a SuperAdmin retried it) is
        # due at once.
        self._tried_at = {
            job_id: tried for job_id, tried in self._tried_at.items() if job_id in listed
        }
        self._placement = placement
        self._changed.set()

    def runtime_file_written(self, written: WrittenRuntimeFile) -> None:
        self._written = written
        self._changed.set()

    def notice_change(self) -> None:
        """Something about the placement changed (its process's state): look at the jobs again."""
        self._changed.set()

    async def drain(self) -> None:
        """Wait until no hook call is in flight, at most its timeout plus `DRAIN_MARGIN_SECONDS`.

        The caller has made sure no new job is claimed (an upgrade in `maintenance`). A call
        still running afterwards is cut short when the process stops, and reported as stopped.
        """
        while not self._idle.is_set() and self._call_deadline is not None:
            remaining = self._call_deadline - time.monotonic()
            if remaining <= 0:
                return
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._idle.wait(), remaining)

    async def _loop(self) -> None:
        while True:
            await self._wait_for_change()
            self._changed.clear()
            ready = self._ready_job()
            if ready is None:
                continue
            job, process = ready
            try:
                await self._run(job, process)
            except Exception:
                # The agent runs every plugin: one hook's unexpected error must not stop the
                # runner. The job was marked tried, so it is not retried at once.
                logger.exception(
                    "Plugin {}: running hook job {} failed",
                    self._placement.plugin_identifier,
                    job.job_id,
                )
            # Another job may be waiting.
            self._changed.set()

    async def _wait_for_change(self) -> None:
        """Wait for a change, or until a job just tried may be claimed again."""
        now = time.monotonic()
        # Only waits still to run: a job whose wait is over but whose plugin is not ready waits
        # for a change like any other.
        retries = [
            remaining
            for job in self._placement.hook_jobs
            if job.job_id in self._tried_at
            and (remaining := self._tried_at[job.job_id] + RECLAIM_AFTER_SECONDS - now) > 0
        ]
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._changed.wait(), min(retries) if retries else None)

    def _ready_job(self) -> tuple[DesiredHookJob, int] | None:
        """The oldest listed job not just tried, and the process to call, if the plugin is ready."""
        now = time.monotonic()
        job = next(
            (
                job
                for job in self._placement.hook_jobs
                if now - self._tried_at.get(job.job_id, -math.inf) >= RECLAIM_AFTER_SECONDS
            ),
            None,
        )
        if job is None:
            return None
        process = self._ready_process(job)
        return None if process is None else (job, process)

    def _ready_process(self, job: DesiredHookJob) -> int | None:
        placement, written = self._placement, self._written
        if placement.desired_state != "running":
            return None
        if written is None or written.credentials_revision != placement.credentials_revision:
            return None
        if (
            job.kind not in KEYLESS_HOOK_KINDS
            and job.organization_id not in written.organization_ids
        ):
            return None
        status = self._supervisor.status()
        if (status.observed_state, status.health) != ("running", "ok"):
            return None
        return self._supervisor.running_process()

    async def _run(self, job: DesiredHookJob, process: int) -> None:
        self._tried_at[job.job_id] = time.monotonic()
        # Busy from the claim on: a drain waits for the claim's answer, then for the call.
        self._idle.clear()
        self._call_deadline = time.monotonic() + CLAIM_SECONDS
        try:
            called = await self._claim_and_call(job)
        finally:
            self._idle.set()
            self._call_deadline = None
        if called is None:
            return
        invocation, outcome = called
        identifier = self._placement.plugin_identifier
        if not outcome.succeeded and self._supervisor.running_process() != process:
            outcome = replace(outcome, error=self._why_the_process_went())
        if outcome.succeeded:
            logger.info(
                "Plugin {}: hook job {} attempt {} succeeded in {} ms",
                identifier,
                invocation.job_id,
                invocation.attempt,
                outcome.duration_ms,
            )
        else:
            logger.warning(
                "Plugin {}: hook job {} attempt {} failed after {} ms: {}",
                identifier,
                invocation.job_id,
                invocation.attempt,
                outcome.duration_ms,
                outcome.error,
            )
        await deliver_result(self._django, invocation.job_id, result_of(invocation, outcome))

    async def _claim_and_call(
        self, job: DesiredHookJob
    ) -> tuple[HookInvocation, HookOutcome] | None:
        identifier = self._placement.plugin_identifier
        try:
            invocation = await self._django.claim_hook_job(job.job_id)
        except NodeApiError as error:
            logger.warning(
                "Plugin {}: could not claim hook job {}: {}", identifier, job.job_id, error
            )
            return None
        if invocation is None:
            return None
        logger.info(
            "Plugin {}: calling its {} hook, job {} attempt {}, organization {}",
            identifier,
            invocation.kind,
            invocation.job_id,
            invocation.attempt,
            invocation.organization_id,
        )
        started = time.monotonic()
        self._call_deadline = started + invocation.timeout_seconds + DRAIN_MARGIN_SECONDS
        try:
            return invocation, await self._caller.call(self._placement.runtime.port, invocation)
        except asyncio.CancelledError:
            await self._report_stopped(invocation, started)
            raise

    def _why_the_process_went(self) -> str:
        # update() has the new desired placement before converge acts on it, so a stop that
        # converge makes for it already shows here.
        if self._placement.desired_state != "running":
            return STOPPED_DURING_HOOK
        return RESTARTED_DURING_HOOK

    async def _report_stopped(self, invocation: HookInvocation, started: float) -> None:
        outcome = HookOutcome(
            succeeded=False,
            error=STOPPED_DURING_HOOK,
            http_status=None,
            duration_ms=round((time.monotonic() - started) * 1000),
        )
        try:
            async with asyncio.timeout(STOPPED_RESULT_SECONDS):
                await self._django.send_hook_result(
                    invocation.job_id, result_of(invocation, outcome)
                )
        except (NodeApiError, TimeoutError) as error:
            # django_app fails the job itself once its deadline has passed.
            logger.warning(
                "Plugin {}: could not report hook job {} as stopped: {}",
                self._placement.plugin_identifier,
                invocation.job_id,
                str(error) or "no answer in time",
            )


def result_of(invocation: HookInvocation, outcome: HookOutcome) -> HookResult:
    return HookResult(
        attempt=invocation.attempt,
        outcome="succeeded" if outcome.succeeded else "failed",
        error=outcome.error,
        http_status=outcome.http_status,
        duration_ms=outcome.duration_ms,
    )


async def deliver_result(
    django: DjangoNodeClient,
    job_id: int,
    result: HookResult,
    *,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> bool:
    """Post a hook result, retrying while django_app cannot be reached, for up to 120 s.

    Returns whether django_app took it. A refusal (409: the job is no longer running with this
    attempt) is not retried; when the result never arrives, django_app fails the job itself
    once its deadline has passed.
    """
    give_up_at = clock() + RESULT_DELIVERY_SECONDS
    delay = RESULT_FIRST_RETRY_SECONDS
    while True:
        try:
            await django.send_hook_result(job_id, result)
            return True
        except NodeApiError as error:
            if not error.transient or clock() + delay > give_up_at:
                logger.warning("Could not report the result of hook job {}: {}", job_id, error)
                return False
        await sleep(delay)
        delay = min(delay * 2, RESULT_LONGEST_RETRY_SECONDS)
