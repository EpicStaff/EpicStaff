"""Drains the worker's result queue and forwards each result to the publisher.

A transport pump: it moves finished executions from the in-process queue out through
the publisher, then marks each one DONE in the execution registry. A publish failure is
logged and the pump carries on -- one bad result must not stall the rest.
"""

import asyncio

from common.contracts import ExecutionResultMessage
from loguru import logger

from manager.application.registry import ExecutionRegistry
from manager.infrastructure.transport.result_publisher import AbstractResultPublisher

__all__ = ["ResultConsumer"]


class ResultConsumer:
    def __init__(
        self,
        queue: asyncio.Queue[ExecutionResultMessage],
        publisher: AbstractResultPublisher,
        registry: ExecutionRegistry,
    ):
        self._queue = queue
        self._publisher = publisher
        self._registry = registry

    async def run(self) -> None:
        while True:
            message = await self._queue.get()
            try:
                await self._publisher.publish(message)
            except Exception as error:
                # Type only: the error text may quote the result, which is user output.
                logger.error(
                    "Failed to publish result for {}: {}",
                    message.execution_id,
                    type(error).__name__,
                )
            finally:
                # Finished after the publish, so DONE never shows before the result is
                # out. Finished even when the publish failed: the producer's next status
                # check then gets DONE and, a minute later, 404 -- it fails fast instead
                # of waiting on a result that is never coming.
                self._registry.finish(message.execution_id, ran=message.ran)
