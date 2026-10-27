"""The worker's outbound port: hand a finished execution back to the manager.

The worker does no external I/O of its own -- it executes and returns. The result
(and any storage mutations the run reported) go back through this port; the manager
is what publishes them onward. The adapter owns the transport and the wire shape.
"""

import abc

from worker.domain.models import ExecutionResult, StorageMutations

__all__ = ["AbstractResultSink"]


class AbstractResultSink(abc.ABC):
    @abc.abstractmethod
    async def send(
        self, result: ExecutionResult, mutations: StorageMutations | None = None
    ) -> None:
        """Hand the execution's result, and any storage mutations, to the manager."""
