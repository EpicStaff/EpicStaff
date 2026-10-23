"""Consumes dispatched jobs and runs them across a bounded number of slots.

The worker's primary (driving) adapter: every job the manager dispatches is already
gated to a COMPLETED venv, so this just pulls and executes. Concurrency is the
worker's own: at most ``concurrency`` jobs run at once; a free slot is taken before
the next job is pulled, leaving the rest queued. One job failing never takes the
consumer down -- it is logged and the slot is freed.
"""

import asyncio

from loguru import logger

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

    async def run(self) -> None:
        while True:
            await self._slots.acquire()
            job = await self._job_source.get()
            task = asyncio.create_task(self._handle(job))
            self._running.add(task)
            task.add_done_callback(self._running.discard)

    async def _handle(self, job: Job) -> None:
        try:
            await self._orchestrator.execute(job)
        except Exception:
            logger.exception("Worker failed to handle job {}", job.execution_id)
        finally:
            self._slots.release()
