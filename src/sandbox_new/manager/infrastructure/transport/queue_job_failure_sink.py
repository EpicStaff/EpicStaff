"""Routes a pre-run job failure down the same result path as a real execution.

Builds a failed `ExecutionResultMessage`, its `error` coded with the reason the job
never ran, and puts it on the result queue, so it flows through the result consumer
and publisher exactly like a worker result -- the consumer never has to know the job
never reached the worker.
"""

import asyncio

from common.contracts import ExecutionResultMessage
from foundation.schemas import ErrorDetailSchema

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
                returncode=1,
                error=ErrorDetailSchema(code=not_run_reason, detail=message),
                reply_to_crew_channel=reply_to_crew_channel,
                session_id=session_id,
                not_run_reason=not_run_reason,
            )
        )
