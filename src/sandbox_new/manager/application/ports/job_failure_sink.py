"""The port the orchestrator uses to report a job that never reached the worker.

When a job's venv has failed to build, the job cannot run -- but the consumer still
expects an outcome. The orchestrator reports it through this port as a failed result,
without knowing how it is delivered; the adapter routes it down the same result path
as a real execution.
"""

import abc

from manager.domain.types import NotRunReason

__all__ = ["AbstractJobFailureSink"]


class AbstractJobFailureSink(abc.ABC):
    @abc.abstractmethod
    async def fail(
        self,
        execution_id: str,
        message: str,
        *,
        session_id: int | None,
        not_run_reason: NotRunReason,
        reply_to_crew_channel: bool,
    ) -> None:
        """Report that ``execution_id`` failed before it could run, with ``message``.

        Args:
            not_run_reason: Why it never ran; reported as the outcome of the result's
                BENCH checkpoint.
            reply_to_crew_channel: Route the failed result to crew's own result channel,
                the same way a real execution's result is routed. A job that never ran
                still has to answer on the channel its submitter is listening to.
        """
