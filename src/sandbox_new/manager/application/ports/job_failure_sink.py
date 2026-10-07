"""The port the orchestrator uses to report a job that never reached the worker.

When a job's venv has failed to build, the job cannot run -- but the consumer still
expects an outcome. The orchestrator reports it through this port as a failed result,
without knowing how it is delivered; the adapter routes it down the same result path
as a real execution.
"""

import abc

__all__ = ["AbstractJobFailureSink"]


class AbstractJobFailureSink(abc.ABC):
    @abc.abstractmethod
    async def fail(self, execution_id: str, message: str) -> None:
        """Report that ``execution_id`` failed before it could run, with ``message``."""
