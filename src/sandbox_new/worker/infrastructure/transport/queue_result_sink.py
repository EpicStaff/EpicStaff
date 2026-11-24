"""In-process result sink: the worker-to-manager side of the transport.

Encodes the domain result (and any mutations) into a wire ``ExecutionResultMessage``
and puts it on the shared result queue the manager drains. The wire shape lives in the
codec, not in the application.
"""

import asyncio

from common.contracts import ExecutionResultMessage

from worker.application.ports.result_sink import AbstractResultSink
from worker.domain.models import ExecutionResult, StorageMutations
from worker.infrastructure.transport.codec import encode_result

__all__ = ["QueueResultSink"]


class QueueResultSink(AbstractResultSink):
    def __init__(self, queue: asyncio.Queue[ExecutionResultMessage]):
        self._queue = queue

    async def send(
        self, result: ExecutionResult, mutations: StorageMutations | None = None
    ) -> None:
        await self._queue.put(encode_result(result, mutations))
