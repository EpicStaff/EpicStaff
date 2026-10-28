"""The port for publishing finished executions onward from the manager.

The worker returns results to the manager; the manager is what publishes them to the
outside world (the result channel today, storage mutations on their own channel). The
real transport adapter is `RedisResultPublisher`; `LoggingResultPublisher` is a
stand-in that logs instead of publishing, for wiring the runtime without Redis.
"""

import abc

from common.contracts import ExecutionResultMessage
from loguru import logger

__all__ = ["AbstractResultPublisher", "LoggingResultPublisher"]


class AbstractResultPublisher(abc.ABC):
    @abc.abstractmethod
    async def publish(self, result: ExecutionResultMessage) -> None:
        pass


class LoggingResultPublisher(AbstractResultPublisher):
    async def publish(self, result: ExecutionResultMessage) -> None:
        mutation_count = 0 if result.mutations is None else len(result.mutations.mutations)
        logger.info(
            "Execution {} finished: returncode={}, result={}, mutations={}",
            result.execution_id,
            result.returncode,
            "present" if result.result is not None else "none",
            mutation_count,
        )
