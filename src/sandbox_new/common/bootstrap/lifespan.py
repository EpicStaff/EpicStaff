"""The neutral composition root that owns the manager<->worker seam.

The manager and worker are one process today, bridged by two in-memory queues. This
module is the single place that owns that bridge: it creates the queues, builds the
transports over them, and starts the background runners (worker job consumer, result
consumer, held-job releaser). Splitting the two services later -- replacing the
queues with a network transport -- is a change confined to this file; no application
or domain code moves.

The job-intake singletons the request path needs are published on ``app.state`` so
controllers reach them through Litestar's ``State`` injection, never through a module
global or an import of this layer.
"""

import asyncio
import contextlib
from dataclasses import dataclass

import settings
from foundation.utils.litestar import lifespan
from litestar import Litestar
from manager.application.holding import JobHoldingRegistry
from manager.application.orchestrators import JobOrchestrator
from manager.infrastructure.database.unit_of_work import PiccoloUnitOfWork
from manager.infrastructure.transport.queue_job_dispatcher import QueueJobDispatcher
from manager.infrastructure.transport.queue_job_failure_sink import QueueJobFailureSink
from manager.infrastructure.transport.redis_result_publisher import RedisResultPublisher
from manager.infrastructure.transport.result_consumer import ResultConsumer
from manager.presentation.held_job_releaser import HeldJobReleaser
from redis.asyncio import Redis
from worker.bootstrap.di import build_job_consumer

from common.contracts import ExecutionJobMessage, ExecutionResultMessage

__all__ = ["JobIntake"]

_RELEASE_INTERVAL_SECONDS = 2.0


@dataclass(frozen=True)
class JobIntake:
    """The singletons the request path needs to accept a job.

    Built once at startup and read off ``app.state`` by the execution controller.
    """

    dispatcher: QueueJobDispatcher
    holding: JobHoldingRegistry
    failure_sink: QueueJobFailureSink


@lifespan.on_startup
async def start_runtime(app: Litestar) -> None:
    job_queue: asyncio.Queue[ExecutionJobMessage] = asyncio.Queue()
    result_queue: asyncio.Queue[ExecutionResultMessage] = asyncio.Queue()

    holding = JobHoldingRegistry()
    dispatcher = QueueJobDispatcher(job_queue)
    failure_sink = QueueJobFailureSink(result_queue)
    app.state.job_intake = JobIntake(dispatcher, holding, failure_sink)

    redis = Redis(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        username=settings.REDIS_USER or None,
        password=settings.REDIS_PASSWORD or None,
    )
    app.state.runtime_redis = redis

    runners = [
        build_job_consumer(job_queue=job_queue, result_queue=result_queue),
        ResultConsumer(
            result_queue,
            RedisResultPublisher(
                redis,
                result_channel=settings.JOB_RESULT_CHANNEL,
                mutation_channel=settings.STORAGE_MUTATION_CHANNEL,
            ),
        ),
        HeldJobReleaser(
            JobOrchestrator(PiccoloUnitOfWork(), dispatcher, holding, failure_sink),
            interval=_RELEASE_INTERVAL_SECONDS,
        ),
    ]
    app.state.runtime_tasks = [asyncio.create_task(runner.run()) for runner in runners]


@lifespan.on_shutdown
async def stop_runtime(app: Litestar) -> None:
    tasks: list[asyncio.Task] = getattr(app.state, "runtime_tasks", [])
    for task in tasks:
        task.cancel()
    for task in tasks:
        with contextlib.suppress(asyncio.CancelledError):
            await task

    redis: Redis | None = getattr(app.state, "runtime_redis", None)
    if redis is not None:
        await redis.aclose()
