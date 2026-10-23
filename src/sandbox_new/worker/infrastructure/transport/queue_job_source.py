"""In-process job source: the manager-to-worker side of the transport.

Wraps the shared queue the manager dispatches onto. Decodes the wire
``ExecutionJobMessage`` into a domain ``Job`` at the boundary, so the wire shape
never reaches the application. Swapping this for a network source later does not
touch the pipeline.
"""

import asyncio

from common.contracts import ExecutionJobMessage

from worker.application.ports.job_source import AbstractJobSource
from worker.domain.models import Job

__all__ = ["QueueJobSource"]


class QueueJobSource(AbstractJobSource):
    def __init__(self, queue: asyncio.Queue[ExecutionJobMessage]):
        self._queue = queue

    async def get(self) -> Job:
        message = await self._queue.get()
        return Job(**message.model_dump())
