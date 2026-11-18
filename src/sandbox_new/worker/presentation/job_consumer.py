"""Consumes dispatched jobs, taking an admission-gate slot before each pull.

The worker's primary (driving) adapter. The slot comes first: the pull itself is the
capacity signal -- the manager counts a waiting long-poll as a free slot -- so a job
handed to this worker always has a slot waiting and is never parked here against its
queue deadline. Every job ends with a result: one that expired in the queue, could not
be decoded, or whose run blew up is failed through the orchestrator rather than
dropped, and failing it reuses the already-held slot for the next pull. One bad job or
message never ends the loop.

Messages here are logged with the execution id and the exception type only: an
exception's text may quote the job's code, secrets or output.
"""

import asyncio
import time
from collections.abc import Callable

from loguru import logger
from src.shared.bench_log import BENCH_LEVEL

from worker.application.orchestrator import ExecutionOrchestrator
from worker.application.ports import AbstractAdmissionGate, AbstractJobSource, UndecodableJobError
from worker.domain.models import Job

__all__ = ["JobConsumer"]

_EXPIRED_MESSAGE = "Sandbox overloaded: the job waited {waited} s in the queue and was not run."
_UNDECODABLE_MESSAGE = "Sandbox could not read the job; it was not run."
_RUN_FAILED_MESSAGE = "Sandbox failed to run the job."


class JobConsumer:
    """Pull jobs, admit them through the gate, run each as its own task.

    Args:
        queue_timeout: Seconds a job may wait in the queue, counted from its
            `queued_at`, before it is failed instead of run.
        clock: Wall clock, the one the manager stamps `queued_at` with.
    """

    def __init__(
        self,
        job_source: AbstractJobSource,
        orchestrator: ExecutionOrchestrator,
        gate: AbstractAdmissionGate,
        *,
        queue_timeout: float,
        clock: Callable[[], float] = time.time,
    ):
        self._job_source = job_source
        self._orchestrator = orchestrator
        self._gate = gate
        self._queue_timeout = queue_timeout
        self._clock = clock
        self._running: set[asyncio.Task] = set()
        self._executing = 0
        self._held_ids: set[str] = set()

    def held_execution_ids(self) -> set[str]:
        """The executions this worker holds right now; the heartbeat reports them.

        A job that will run enters the moment its pull completes and leaves when its
        run has ended and its result was handed to the sink, so the manager never sees
        a held job missing from the report. Jobs failed without running (expired,
        undecodable) are never held: their failure is on its way, and if the manager
        releases one as worker-lost first, the outcome is still a failure.
        """
        return set(self._held_ids)

    async def run(self) -> None:
        while True:
            try:
                await self._start_next()
            except Exception as error:
                logger.error("Worker loop turn failed: {}", type(error).__name__)

    async def _start_next(self) -> None:
        await self._gate.acquire()
        try:
            job = await self._next_runnable_job()
        except BaseException:
            self._gate.release()
            raise
        self._held_ids.add(job.execution_id)
        task = asyncio.create_task(self._run(job))
        self._running.add(task)
        task.add_done_callback(self._running.discard)

    async def _next_runnable_job(self) -> Job:
        """Pull until a job that may still run; the rest are failed on the held slot."""
        while True:
            try:
                job = await self._job_source.get()
            except UndecodableJobError as error:
                logger.error("Job {} could not be decoded; failing it", error.execution_id)
                await self._orchestrator.fail(
                    error.execution_id,
                    _UNDECODABLE_MESSAGE,
                    session_id=error.session_id,
                    reply_to_crew_channel=error.reply_to_crew_channel,
                )
                continue
            if self._has_expired(job):
                await self._fail_expired(job)
                continue
            return job

    async def _run(self, job: Job) -> None:
        # Counted here, not from `_running`: a burst of jobs creates every task before
        # the first one starts, so the set already holds jobs that are not running yet.
        self._executing += 1
        logger.log(
            BENCH_LEVEL,
            "bench {checkpoint}",
            checkpoint="exec_start",
            session_id=job.session_id,
            execution_id=job.execution_id,
            running=self._executing,
        )
        try:
            await self._orchestrator.execute(job)
        except Exception as error:
            logger.error("Worker failed to run job {}: {}", job.execution_id, type(error).__name__)
            try:
                await self._orchestrator.fail(
                    job.execution_id,
                    _RUN_FAILED_MESSAGE,
                    session_id=job.session_id,
                    reply_to_crew_channel=job.reply_to_crew_channel,
                )
            except Exception as fail_error:
                logger.error(
                    "Could not report the failed run of job {}: {}",
                    job.execution_id,
                    type(fail_error).__name__,
                )
        finally:
            self._held_ids.discard(job.execution_id)
            self._executing -= 1
            self._gate.release()

    def _deadline(self, job: Job) -> float | None:
        return None if job.queued_at is None else job.queued_at + self._queue_timeout

    def _has_expired(self, job: Job) -> bool:
        deadline = self._deadline(job)
        return deadline is not None and self._clock() > deadline

    async def _fail_expired(self, job: Job) -> None:
        waited = int(self._clock() - job.queued_at)
        logger.warning("Job {} expired after {} s in the queue; not run", job.execution_id, waited)
        logger.log(
            BENCH_LEVEL,
            "bench {checkpoint}",
            checkpoint="exec_expired",
            session_id=job.session_id,
            execution_id=job.execution_id,
            waited_s=waited,
        )
        await self._orchestrator.fail(
            job.execution_id,
            _EXPIRED_MESSAGE.format(waited=waited),
            session_id=job.session_id,
            reply_to_crew_channel=job.reply_to_crew_channel,
            not_run_reason="overloaded",
        )
