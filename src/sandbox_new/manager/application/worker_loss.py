"""Fail the executions whose worker is gone, down the ordinary result path.

An assignment is released when its worker run is gone: restarted under a new boot id,
silent past the heartbeat threshold, or repeatedly not reporting a job it was handed.
Every such release must end in a result (every path does). The text is
fixed: a worker lost mid-job can leave nothing quotable that is safe to show.
"""

from manager.application.ports import AbstractJobFailureSink
from manager.application.registry import LostJob

__all__ = ["WORKER_LOST_MESSAGE", "fail_lost_jobs"]

WORKER_LOST_MESSAGE = "Sandbox worker was lost; the job may not have finished."


async def fail_lost_jobs(lost_jobs: list[LostJob], failure_sink: AbstractJobFailureSink) -> None:
    """Send the fixed worker-lost failure result for each lost job."""
    for job in lost_jobs:
        await failure_sink.fail(
            job.execution_id,
            WORKER_LOST_MESSAGE,
            session_id=job.session_id,
            not_run_reason="worker_lost",
            reply_to_crew_channel=job.reply_to_crew_channel,
        )
