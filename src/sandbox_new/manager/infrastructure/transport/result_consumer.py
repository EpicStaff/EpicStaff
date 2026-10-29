"""Drains the worker's result queue and forwards each result to the publisher.

A transport pump: it owns no business logic, it just moves finished executions from
the in-process queue out through the publisher. A publish failure is logged and the
pump carries on -- one bad result must not stall the rest.
"""

import asyncio

from common.contracts import ExecutionResultMessage
from loguru import logger

from manager.infrastructure.transport.result_publisher import AbstractResultPublisher

__all__ = ["ResultConsumer"]


class ResultConsumer:
    def __init__(
        self,
        queue: asyncio.Queue[ExecutionResultMessage],
        publisher: AbstractResultPublisher,
    ):
        self._queue = queue
        self._publisher = publisher

    async def run(self) -> None:
        while True:
            message = await self._queue.get()
            try:
                await self._publisher.publish(message)
            except Exception:
                logger.exception("Failed to publish result for {}", message.execution_id)
