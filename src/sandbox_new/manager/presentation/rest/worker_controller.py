"""The manager's side of the manager/worker seam.

The worker drives it: it long-polls for a job whenever its run gate has a free slot,
posts the result back when a run ends, and heartbeats in between so a saturated worker
that neither pulls nor finishes anything still proves it is alive. Nothing here is for
producers, so the routes stay out of the OpenAPI schema. Every route requires the
internal bearer token -- the job payloads handed out carry plaintext secrets -- and
carries the worker run's boot id, which is how the manager tells a live run from a dead
one.

A handed-out job is recorded as assigned to the pulling boot id. A pull under a new
boot id proves the old run died, so its assigned jobs are failed right here, before the
new run gets work; a request under a superseded boot id is a zombie long-poll whose
connection died, and is never handed a job. Jobs are never timed against their own
duration -- a legitimate run may take hours; the silence-based backstop lives in the
worker-loss sweeper.
"""

import asyncio

from common.contracts import ExecutionJobMessage, ExecutionResultMessage, WorkerHeartbeatMessage
from litestar import Controller, Response, get, post, status_codes
from litestar.params import Parameter
from loguru import logger

from manager.application.ports import AbstractJobFailureSink
from manager.application.registry import ExecutionRegistry
from manager.application.worker_contact import WorkerContact
from manager.application.worker_loss import fail_lost_jobs
from manager.presentation.rest.guards import verify_internal_token

__all__ = ["LONG_POLL_SECONDS", "WorkerController"]

# Seconds an empty pull waits for a job before answering 204 and letting the worker
# poll again. Kept under typical proxy/server idle timeouts.
LONG_POLL_SECONDS = 25.0
# An assignment this old and absent from the worker's heartbeat report is a lost
# hand-off. Three heartbeat intervals: at least two beats have passed since the pull
# response could have arrived, so a healthy worker has reported the job twice by now.
UNREPORTED_ASSIGNMENT_GRACE_SECONDS = 30.0

BOOT_ID_HEADER = Parameter(
    header="X-Worker-Boot-Id",
    description="UUID of the worker process run making the request.",
)


class WorkerController(Controller):
    path = "/worker"
    include_in_schema = False
    guards = [verify_internal_token]
    # Litestar's default caps request bodies at 10 MB, below SANDBOX_MAX_RESULT_SIZE
    # (16 MB) plus stdout/stderr and JSON escaping -- a successful large result would be
    # refused with 413 and lost. The routes are token-guarded and the worker already
    # bounds every part it reads back, so no second cap is kept here.
    request_max_body_size = None

    @get("/jobs")
    async def pull_job(
        self,
        execution_registry: ExecutionRegistry,
        worker_contact: WorkerContact,
        job_queue: asyncio.Queue,
        job_failure_sink: AbstractJobFailureSink,
        boot_id: str = BOOT_ID_HEADER,
    ) -> Response:
        """Hand the worker one queued job, or 204 when none arrives in time.

        The job is marked assigned to this boot id before the response is sent. A
        response lost on the way to the worker is caught by the heartbeat report: the
        worker never lists that execution among the ids it holds, and the assignment is
        released once it is old enough.

        Raises:
            NotAuthorizedException: No valid internal token, rendered as 401.
        """
        if not worker_contact.accept_boot(boot_id):
            # A zombie long-poll of a dead worker run; handing it a job would strand it.
            return Response(content=None, status_code=status_codes.HTTP_204_NO_CONTENT)
        worker_contact.record_seen(boot_id)
        released = execution_registry.release_assignments_not_from(boot_id)
        await fail_lost_jobs(released, job_failure_sink)
        worker_contact.add_waiting_poller()
        try:
            job: ExecutionJobMessage = await asyncio.wait_for(job_queue.get(), LONG_POLL_SECONDS)
        except TimeoutError:
            return Response(content=None, status_code=status_codes.HTTP_204_NO_CONTENT)
        finally:
            worker_contact.remove_waiting_poller()
        if not worker_contact.accept_boot(boot_id):
            # This run died and was superseded while the poll waited. Back to the queue
            # (at the tail: order is already bounded by each job's own queue deadline).
            job_queue.put_nowait(job)
            return Response(content=None, status_code=status_codes.HTTP_204_NO_CONTENT)
        execution_registry.mark_assigned(
            job.execution_id,
            boot_id=boot_id,
            session_id=job.session_id,
            reply_to_crew_channel=job.reply_to_crew_channel,
        )
        return Response(content=job, status_code=status_codes.HTTP_200_OK)

    @post("/results", status_code=status_codes.HTTP_202_ACCEPTED)
    async def push_result(
        self,
        data: ExecutionResultMessage,
        execution_registry: ExecutionRegistry,
        worker_contact: WorkerContact,
        result_queue: asyncio.Queue,
        boot_id: str = BOOT_ID_HEADER,
    ) -> None:
        """Take one finished execution's result; the result consumer publishes it.

        Settling the assignment first makes delivery exactly-once on this side: a retry
        of a POST the manager already accepted, or a result arriving after the job was
        failed as worker-lost, finds no assignment and is dropped -- its node already
        has an outcome, and publishing a second one would duplicate it.

        Raises:
            NotAuthorizedException: No valid internal token, rendered as 401.
        """
        worker_contact.record_seen(boot_id)
        if not execution_registry.settle_assignment(data.execution_id):
            logger.warning(
                "Dropped a result for execution {}: it is not assigned (late or duplicate)",
                data.execution_id,
            )
            return
        await result_queue.put(data)

    @post("/heartbeat", status_code=status_codes.HTTP_204_NO_CONTENT)
    async def heartbeat(
        self,
        data: WorkerHeartbeatMessage,
        execution_registry: ExecutionRegistry,
        worker_contact: WorkerContact,
        job_failure_sink: AbstractJobFailureSink,
        boot_id: str = BOOT_ID_HEADER,
    ) -> None:
        """Record that this worker run is alive and reconcile what it holds.

        The saturated worker's only sign of life: with every slot busy it neither pulls
        nor, during a long run, posts anything. The beat also reports the execution ids
        the worker actually holds: an assignment of this run missing from the report
        had its pull response lost on the way, and nothing else would ever release it
        (the run keeps beating, so it never goes silent). Assignments younger than the
        grace are spared -- a hand-off still in flight is not yet lost.

        Raises:
            NotAuthorizedException: No valid internal token, rendered as 401.
        """
        worker_contact.record_seen(boot_id)
        lost = execution_registry.release_unreported_assignments(
            boot_id,
            set(data.execution_ids),
            min_age=UNREPORTED_ASSIGNMENT_GRACE_SECONDS,
        )
        await fail_lost_jobs(lost, job_failure_sink)
