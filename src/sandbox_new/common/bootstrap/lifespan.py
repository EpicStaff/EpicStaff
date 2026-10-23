"""The neutral composition root that owns the manager<->worker seam.

The manager and worker are one process today, bridged by two in-memory queues. This
module is the single place that owns that bridge: it creates the queues, builds the
transports over them, and starts the background runners (worker job consumer, result
consumer, held-job releaser, admission gate). Splitting the two services later --
replacing the queues with a network transport -- is a change confined to this file; no
application or domain code moves. The one exception is the queue deadline, a
monotonic-clock reading that only means something inside this one process.

The job-intake singletons the request path needs are published on ``app.state`` so
controllers reach them through Litestar's ``State`` injection, never through a module
global or an import of this layer.

Every runner is supervised: one that dies takes the process down with it, so the
container restarts instead of accepting jobs nothing will ever run or answer.
"""

import asyncio
import os
import signal
from collections.abc import Callable
from dataclasses import dataclass

import settings
from foundation.utils.litestar import lifespan
from litestar import Litestar
from loguru import logger
from manager.application.holding import JobHoldingRegistry
from manager.application.intake import IntakeGate
from manager.application.orchestrators import JobOrchestrator
from manager.application.registry import ExecutionRegistry
from manager.infrastructure.database.unit_of_work import PiccoloUnitOfWork
from manager.infrastructure.transport.queue_job_dispatcher import QueueJobDispatcher
from manager.infrastructure.transport.queue_job_failure_sink import QueueJobFailureSink
from manager.infrastructure.transport.redis_result_publisher import RedisResultPublisher
from manager.infrastructure.transport.result_consumer import ResultConsumer
from manager.presentation.held_job_releaser import HeldJobReleaser
from redis.asyncio import Redis
from worker.bootstrap.di import build_admission_gate, build_job_consumer

from common.contracts import ExecutionJobMessage, ExecutionResultMessage

__all__ = ["JobIntake", "supervise"]

_RELEASE_INTERVAL_SECONDS = 2.0


@dataclass(frozen=True)
class JobIntake:
    """The singletons the request path needs to accept a job.

    Built once at startup and read off ``app.state`` by the execution controller and
    its guard.
    """

    dispatcher: QueueJobDispatcher
    holding: JobHoldingRegistry
    failure_sink: QueueJobFailureSink
    registry: ExecutionRegistry
    intake_gate: IntakeGate
    queue_timeout: float
    hold_timeout: float


def _terminate_process() -> None:
    # SIGTERM rather than an exit: uvicorn shuts down gracefully on it, running the
    # shutdown hooks, and the container's restart policy brings the service back.
    os.kill(os.getpid(), signal.SIGTERM)


def supervise(task: asyncio.Task, *, stop: Callable[[], None] = _terminate_process) -> None:
    """Stop the process when `task` ends for any reason other than being cancelled.

    The runners loop forever, so any end -- an exception or a plain return -- means a
    part of the pipeline is gone. Logged with the runner's name and the exception type
    only: the exception's text may quote a job.
    """

    def on_done(finished: asyncio.Task) -> None:
        if finished.cancelled():
            return
        error = finished.exception()
        logger.critical(
            "Runtime runner '{}' stopped ({}); shutting the sandbox down",
            finished.get_name(),
            "returned" if error is None else type(error).__name__,
        )
        stop()

    task.add_done_callback(on_done)


@lifespan.on_startup
async def start_runtime(app: Litestar) -> None:
    job_queue: asyncio.Queue[ExecutionJobMessage] = asyncio.Queue()
    result_queue: asyncio.Queue[ExecutionResultMessage] = asyncio.Queue()

    holding = JobHoldingRegistry()
    registry = ExecutionRegistry()
    admission_gate = build_admission_gate()
    intake_gate = IntakeGate(
        registry,
        admission_gate.has_free_slot,
        max_accepted=settings.MAX_ACCEPTED_EXECUTIONS,
        max_held=settings.MAX_HELD_EXECUTIONS,
        queue_timeout=settings.QUEUE_TIMEOUT,
    )
    dispatcher = QueueJobDispatcher(job_queue)
    failure_sink = QueueJobFailureSink(result_queue)
    app.state.job_intake = JobIntake(
        dispatcher,
        holding,
        failure_sink,
        registry,
        intake_gate,
        settings.QUEUE_TIMEOUT,
        settings.HOLD_TIMEOUT,
    )

    redis = Redis(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        username=settings.REDIS_USER or None,
        password=settings.REDIS_PASSWORD or None,
    )
    app.state.runtime_redis = redis

    runners = {
        "admission gate": admission_gate,
        "job consumer": build_job_consumer(
            job_queue=job_queue, result_queue=result_queue, gate=admission_gate
        ),
        "result consumer": ResultConsumer(
            result_queue,
            RedisResultPublisher(
                redis,
                result_channel=settings.JOB_RESULT_CHANNEL,
                crew_result_channel=settings.CREW_JOB_RESULT_CHANNEL,
                mutation_channel=settings.STORAGE_MUTATION_CHANNEL,
            ),
            registry,
        ),
        "held-job releaser": HeldJobReleaser(
            JobOrchestrator(
                PiccoloUnitOfWork(),
                dispatcher,
                holding,
                failure_sink,
                registry,
                intake_gate,
                queue_timeout=settings.QUEUE_TIMEOUT,
                hold_timeout=settings.HOLD_TIMEOUT,
            ),
            interval=_RELEASE_INTERVAL_SECONDS,
        ),
    }
    app.state.runtime_tasks = []
    for name, runner in runners.items():
        task = asyncio.create_task(runner.run(), name=name)
        supervise(task)
        app.state.runtime_tasks.append(task)


@lifespan.on_shutdown
async def stop_runtime(app: Litestar) -> None:
    tasks: list[asyncio.Task] = getattr(app.state, "runtime_tasks", [])
    for task in tasks:
        task.cancel()
    # A runner that already died is why we are shutting down; its supervisor logged it,
    # so its exception must not abort the rest of this shutdown.
    await asyncio.gather(*tasks, return_exceptions=True)

    redis: Redis | None = getattr(app.state, "runtime_redis", None)
    if redis is not None:
        await redis.aclose()
