"""Consumes dispatched jobs and runs them across a bounded number of slots.

The worker's primary (driving) adapter: every job the manager dispatches is already
gated to a COMPLETED venv, so this just pulls and executes. Concurrency is the
worker's own: at most ``concurrency`` jobs run at once; a free slot is taken before
the next job is pulled, leaving the rest queued. One job failing never takes the
consumer down -- it is logged and the slot is freed.
"""

import asyncio

from loguru import logger
from src.shared.bench_log import BENCH_LEVEL

from worker.application.orchestrator import ExecutionOrchestrator
from worker.application.ports.job_source import AbstractJobSource
from worker.domain.models import Job

__all__ = ["JobConsumer"]


class JobConsumer:
    def __init__(
        self,
        job_source: AbstractJobSource,
        orchestrator: ExecutionOrchestrator,
        *,
        concurrency: int,
    ):
        self._job_source = job_source
        self._orchestrator = orchestrator
        self._slots = asyncio.Semaphore(concurrency)
        self._running: set[asyncio.Task] = set()
        self._executing = 0

    async def run(self) -> None:
        while True:
            await self._slots.acquire()
            job = await self._job_source.get()
            task = asyncio.create_task(self._handle(job))
            self._running.add(task)
            task.add_done_callback(self._running.discard)

    async def _handle(self, job: Job) -> None:
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
        except Exception:
            logger.exception("Worker failed to handle job {}", job.execution_id)
        finally:
            self._executing -= 1
            self._slots.release()
