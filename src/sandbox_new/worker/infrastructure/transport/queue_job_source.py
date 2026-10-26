"""In-process job source: the manager-to-worker side of the transport.

Wraps the shared queue the manager dispatches onto. Decodes the wire
``ExecutionJobMessage`` into a domain ``Job`` at the boundary, so the wire shape
never reaches the application. Swapping this for a network source later does not
touch the pipeline.
"""

import asyncio

from common.contracts import ExecutionJobMessage
from pydantic import ValidationError

from worker.application.ports.job_source import AbstractJobSource, UndecodableJobError
from worker.domain.models import Job

__all__ = ["QueueJobSource"]


class QueueJobSource(AbstractJobSource):
    def __init__(self, queue: asyncio.Queue[ExecutionJobMessage]):
        self._queue = queue

    async def get(self) -> Job:
        message = await self._queue.get()
        try:
            return Job(**message.model_dump())
        except ValidationError:
            # `from None`: the validation error quotes the job's fields, secrets included,
            # and a chained cause would carry it into any traceback that gets logged.
            raise UndecodableJobError(
                message.execution_id,
                reply_to_crew_channel=message.reply_to_crew_channel,
                # The session id may be the very field that failed to decode.
                session_id=message.session_id if isinstance(message.session_id, int) else None,
            ) from None
