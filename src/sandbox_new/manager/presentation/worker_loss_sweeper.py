"""Periodically fails the jobs that will never run or finish.

A restarted worker surfaces its lost jobs at once, through the boot id on its next
pull; this sweeper is the backstop for the other losses -- a worker run that hangs, or
a worker that is gone entirely (container stopped, crash loop, wrong token) so nothing
ever pulls. Liveness is judged from contact alone, never from how long a job runs: a
run may legitimately take hours, so a boot id is declared lost only when nothing has
been heard from it for ``HEARTBEAT_SILENCE_SECONDS``.

Three sweeps per pass:

- Queued jobs past their queue deadline are failed as overloaded. With the worker
  taking a slot before it pulls, a saturated worker never looks at the queue, so the
  deadline the sandbox promises (every queued job runs or fails within
  ``SANDBOX_QUEUE_TIMEOUT``) is enforced here, on the manager's side.
- Assigned jobs of silent boots are released and failed as worker-lost.
- When no worker at all has made contact within the threshold, the whole dispatch queue
  is drained and failed too -- otherwise it would sit "queued" until the producers'
  40-minute backstop.

Every path still ends in a result. A failing pass is logged and the loop carries on.
"""

import asyncio
import time
from collections.abc import Callable

from common.contracts import ExecutionJobMessage
from loguru import logger
from src.shared.bench_log import BENCH_LEVEL

from manager.application.ports import AbstractJobFailureSink
from manager.application.registry import ExecutionRegistry
from manager.application.worker_contact import WorkerContact
from manager.application.worker_loss import WORKER_LOST_MESSAGE, fail_lost_jobs

__all__ = ["HEARTBEAT_SILENCE_SECONDS", "WorkerLossSweeper"]

# A healthy worker makes contact at least every ~10 s (its heartbeat), so six missed
# beats mean it is gone or stuck -- generous enough to ride out GC pauses and load
# spikes on either side.
HEARTBEAT_SILENCE_SECONDS = 60.0

# The same wording the worker uses when it expires a job itself.
_EXPIRED_MESSAGE = "Sandbox overloaded: the job waited {waited} s in the queue and was not run."


class WorkerLossSweeper:
    def __init__(
        self,
        registry: ExecutionRegistry,
        worker_contact: WorkerContact,
        failure_sink: AbstractJobFailureSink,
        job_queue: asyncio.Queue[ExecutionJobMessage],
        *,
        queue_timeout: float,
        interval: float,
        wall_clock: Callable[[], float] = time.time,
    ):
        self._registry = registry
        self._worker_contact = worker_contact
        self._failure_sink = failure_sink
        self._job_queue = job_queue
        self._queue_timeout = queue_timeout
        self._interval = interval
        # Wall clock, the one `queued_at` is stamped with.
        self._wall_clock = wall_clock

    async def run(self) -> None:
        while True:
            await asyncio.sleep(self._interval)
            try:
                await self._expire_overdue_queued_jobs()
                silent_boots = {
                    boot_id
                    for boot_id in self._registry.boots_with_assignments()
                    if self._worker_contact.boot_is_silent(boot_id, HEARTBEAT_SILENCE_SECONDS)
                }
                released = self._registry.release_assignments_of_boots(silent_boots)
                await fail_lost_jobs(released, self._failure_sink)
                if self._worker_contact.worker_is_silent(HEARTBEAT_SILENCE_SECONDS):
                    await self._drain_backlog()
            except Exception:
                logger.exception("Worker-loss sweep pass failed")

    async def _expire_overdue_queued_jobs(self) -> None:
        """Fail the queued jobs past their deadline; the rest go back in order.

        Splitting the queue has no await between taking the jobs and putting the kept
        ones back, so no pull can observe the queue half-rebuilt.
        """
        now = self._wall_clock()
        kept: list[ExecutionJobMessage] = []
        expired: list[ExecutionJobMessage] = []
        while True:
            try:
                job = self._job_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            is_overdue = job.queued_at is not None and now - job.queued_at > self._queue_timeout
            (expired if is_overdue else kept).append(job)
        for job in kept:
            self._job_queue.put_nowait(job)
        for job in expired:
            waited = int(now - job.queued_at)
            logger.warning(
                "Job {} expired after {} s in the queue; not run", job.execution_id, waited
            )
            logger.log(
                BENCH_LEVEL,
                "bench {checkpoint}",
                checkpoint="exec_expired",
                session_id=job.session_id,
                execution_id=job.execution_id,
                waited_s=waited,
            )
            await self._failure_sink.fail(
                job.execution_id,
                _EXPIRED_MESSAGE.format(waited=waited),
                session_id=job.session_id,
                not_run_reason="overloaded",
                reply_to_crew_channel=job.reply_to_crew_channel,
            )

    async def _drain_backlog(self) -> None:
        """Fail every dispatched job: with no worker alive, nothing will ever pull them."""
        while True:
            try:
                job = self._job_queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            logger.warning("No live worker; failing queued job {}", job.execution_id)
            await self._failure_sink.fail(
                job.execution_id,
                WORKER_LOST_MESSAGE,
                session_id=job.session_id,
                not_run_reason="worker_lost",
                reply_to_crew_channel=job.reply_to_crew_channel,
            )
