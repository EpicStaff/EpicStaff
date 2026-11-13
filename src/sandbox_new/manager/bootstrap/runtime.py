"""The manager's composition root: its side of the manager/worker seam.

The worker runs in its own container (its root is ``worker/main.py``); what lives
here is everything the manager owns -- the intake, the registry, held jobs, the two
queues the worker controller serves the seam from, result publishing and the
housekeeping runners. The worker reaches the job queue only through
``GET /worker/jobs`` and the result queue only through ``POST /worker/results``.

What the request path needs is published on ``app.state``: a ``JobOrchestrator``
factory closed over the runtime's singletons and settings, the intake gate (for the
route guard, which cannot take dependencies), the execution registry, the two queues
and the failure sink. The providers in ``manager.bootstrap.di`` hand them to
controllers as Litestar dependencies, so no controller reaches a module global or
imports this layer.

Every runner is supervised: one that dies takes the process down with it, so the
container restarts instead of accepting jobs nothing will ever run or answer.
"""

import asyncio
from collections.abc import Callable
from functools import partial

from common.contracts import ExecutionJobMessage, ExecutionResultMessage
from common.runner import Runner, supervise
from foundation.utils.litestar import lifespan
from litestar import Litestar
from redis.asyncio import Redis

from manager import settings
from manager.application.holding import JobHoldingRegistry
from manager.application.intake import IntakeGate
from manager.application.orchestrators import JobOrchestrator
from manager.application.registry import ExecutionRegistry
from manager.application.worker_contact import WorkerContact
from manager.infrastructure.database.unit_of_work import PiccoloUnitOfWork
from manager.infrastructure.transport.queue_job_dispatcher import QueueJobDispatcher
from manager.infrastructure.transport.queue_job_failure_sink import QueueJobFailureSink
from manager.infrastructure.transport.redis_result_publisher import RedisResultPublisher
from manager.presentation.held_job_releaser import HeldJobReleaser
from manager.presentation.intake_sampler import IntakeSampler
from manager.presentation.result_consumer import ResultConsumer
from manager.presentation.worker_loss_sweeper import WorkerLossSweeper

_RELEASE_INTERVAL_SECONDS = 2.0


@lifespan.on_startup
async def start_runtime(app: Litestar) -> None:
    job_queue: asyncio.Queue[ExecutionJobMessage] = asyncio.Queue()
    result_queue: asyncio.Queue[ExecutionResultMessage] = asyncio.Queue()

    holding = JobHoldingRegistry()
    registry = ExecutionRegistry()
    worker_contact = WorkerContact()
    intake_gate = IntakeGate(
        registry,
        # A parked long-poll is a free slot, but only beyond what is already queued
        # for it: a poller about to wake for a just-dispatched job is not free capacity.
        lambda: worker_contact.waiting_pollers > job_queue.qsize(),
        max_accepted=settings.MAX_ACCEPTED_EXECUTIONS,
        max_held=settings.MAX_HELD_EXECUTIONS,
        queue_timeout=settings.QUEUE_TIMEOUT,
    )
    dispatcher = QueueJobDispatcher(job_queue)
    failure_sink = QueueJobFailureSink(result_queue)
    # The cryptographer is left to the caller: it comes from the dependency providers.
    build_job_orchestrator: Callable[..., JobOrchestrator] = partial(
        JobOrchestrator,
        dispatcher=dispatcher,
        holding=holding,
        failure_sink=failure_sink,
        registry=registry,
        intake_gate=intake_gate,
        hold_timeout=settings.HOLD_TIMEOUT,
    )
    app.state.build_job_orchestrator = build_job_orchestrator
    app.state.intake_gate = intake_gate
    app.state.execution_registry = registry
    app.state.worker_contact = worker_contact
    app.state.job_queue = job_queue
    app.state.result_queue = result_queue
    app.state.job_failure_sink = failure_sink

    redis = Redis(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        username=settings.REDIS_USER or None,
        password=settings.REDIS_PASSWORD or None,
    )
    app.state.runtime_redis = redis

    runners: dict[str, Runner] = {
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
            build_job_orchestrator(
                PiccoloUnitOfWork(),
                # Resolved through the app's provider, so it is the instance requests get.
                cryptographer=await app.dependencies["cryptographer"](),
            ),
            interval=_RELEASE_INTERVAL_SECONDS,
        ),
        "worker-loss sweeper": WorkerLossSweeper(
            registry,
            worker_contact,
            failure_sink,
            job_queue,
            queue_timeout=settings.QUEUE_TIMEOUT,
            interval=_RELEASE_INTERVAL_SECONDS,
        ),
        "intake sampler": IntakeSampler(registry),
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
