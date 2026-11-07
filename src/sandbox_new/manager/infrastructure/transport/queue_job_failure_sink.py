"""Routes a pre-run job failure down the same result path as a real execution.

Builds a failed `ExecutionResultMessage` and puts it on the result queue, so it flows
through the result consumer and publisher exactly like a worker result -- the
consumer never has to know the job never reached the worker.
"""

import asyncio

from common.contracts import ExecutionResultMessage
from src.shared.models.code_failure import CodeFailure

from manager.application.ports import AbstractJobFailureSink

__all__ = ["QueueJobFailureSink"]


class QueueJobFailureSink(AbstractJobFailureSink):
    def __init__(self, queue: asyncio.Queue[ExecutionResultMessage]):
        self._queue = queue

    async def fail(
        self,
        execution_id: str,
        failure: CodeFailure,
        *,
        reference: str | None,
        session_id: int | None,
        reply_to_crew_channel: bool,
    ) -> None:
        await self._queue.put(
            ExecutionResultMessage(
                execution_id=execution_id,
                stderr=failure.detail,
                returncode=1,
                reply_to_crew_channel=reply_to_crew_channel,
                ran=False,
                session_id=session_id,
                failure=failure,
                reference=reference,
            )
        )
