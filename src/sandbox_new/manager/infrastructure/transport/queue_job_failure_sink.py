"""Routes a pre-run job failure down the same result path as a real execution.

Builds a failed `ExecutionResultMessage` and puts it on the result queue, so it flows
through the result consumer and publisher exactly like a worker result -- the
consumer never has to know the job never reached the worker.
"""

import asyncio

from common.contracts import ExecutionResultMessage

from manager.application.ports import AbstractJobFailureSink
from manager.domain.types import NotRunReason

__all__ = ["QueueJobFailureSink"]


class QueueJobFailureSink(AbstractJobFailureSink):
    def __init__(self, queue: asyncio.Queue[ExecutionResultMessage]):
        self._queue = queue

    async def fail(
        self,
        execution_id: str,
        message: str,
        *,
        session_id: int | None,
        not_run_reason: NotRunReason,
        reply_to_crew_channel: bool,
    ) -> None:
        await self._queue.put(
            ExecutionResultMessage(
                execution_id=execution_id,
                stderr=message,
                returncode=1,
                reply_to_crew_channel=reply_to_crew_channel,
                session_id=session_id,
                not_run_reason=not_run_reason,
            )
        )
