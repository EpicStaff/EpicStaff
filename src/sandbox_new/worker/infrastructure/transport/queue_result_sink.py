"""In-process result sink: the worker-to-manager side of the transport.

Encodes the domain result (and any mutations) into a wire ``ExecutionResultMessage``
and puts it on the shared result queue the manager drains. The wire shape lives here,
not in the application.
"""

import asyncio

from common.contracts import ExecutionResultMessage, StorageMutationsMessage

from worker.application.ports.result_sink import AbstractResultSink
from worker.domain.models import ExecutionResult, StorageMutations

__all__ = ["QueueResultSink"]


class QueueResultSink(AbstractResultSink):
    def __init__(self, queue: asyncio.Queue[ExecutionResultMessage]):
        self._queue = queue

    async def send(
        self, result: ExecutionResult, mutations: StorageMutations | None = None
    ) -> None:
        mutations_message = None
        if mutations is not None:
            mutations_message = StorageMutationsMessage(
                org_prefix=mutations.org_prefix,
                session_id=mutations.session_id,
                mutations=mutations.mutations,
            )
        message = ExecutionResultMessage(
            execution_id=result.execution_id,
            result=result.result,
            stdout=result.stdout,
            stderr=result.stderr,
            returncode=result.returncode,
            mutations=mutations_message,
        )
        await self._queue.put(message)
