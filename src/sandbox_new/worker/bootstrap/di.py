"""Assembles the worker runtime from settings and the shared queues.

The composition root for the worker: it wires the execution pipeline (every step in
order), the storage-credentials adapter, the queue source/sink, and the job consumer.
The pipeline is stateless and reused across jobs -- per-job state lives in the context.
"""

import asyncio

import settings
from common.contracts import ExecutionJobMessage, ExecutionResultMessage

from worker.application.orchestrator import ExecutionOrchestrator
from worker.application.pipeline import Pipeline
from worker.application.ports.storage_credentials import AbstractStorageCredentials
from worker.application.steps import BuildIsolationPlan, ProvisionStorageStep
from worker.infrastructure.execution.steps import (
    CaptureMutationsStep,
    CaptureResultStep,
    LaunchStep,
    PrepareWorkspaceStep,
    ResolveVenvStep,
    WrapCodeStep,
)
from worker.infrastructure.isolation.probe import LandlockIsolationProbe
from worker.infrastructure.storage.credentials import MinioStorageCredentials
from worker.infrastructure.transport.queue_job_source import QueueJobSource
from worker.infrastructure.transport.queue_result_sink import QueueResultSink
from worker.presentation.job_consumer import JobConsumer

__all__ = ["build_job_consumer", "build_pipeline"]


def build_pipeline(credentials: AbstractStorageCredentials) -> Pipeline:
    return (
        Pipeline()
        .register(ResolveVenvStep(venvs_dir=settings.VENVS_DIR))
        .register(
            PrepareWorkspaceStep(
                executions_dir=settings.EXECUTIONS_DIR,
                savefiles_root=settings.SAVEFILES_DIR,
            )
        )
        .register(
            ProvisionStorageStep(
                credentials,
                storage_endpoint=settings.STORAGE_ENDPOINT,
                storage_bucket=settings.STORAGE_BUCKET,
            )
        )
        .register(WrapCodeStep())
        .register(
            BuildIsolationPlan(
                LandlockIsolationProbe(),
                require_isolation=settings.REQUIRE_ISOLATION,
                block_network=settings.BLOCK_NETWORK,
                require_signal_isolation=settings.REQUIRE_SIGNAL_ISOLATION,
                storage_port=settings.STORAGE_PORT,
            )
        )
        .register(LaunchStep(default_timeout=settings.EXECUTION_TIMEOUT))
        .register(CaptureMutationsStep())
        .register(CaptureResultStep(mask_secrets=settings.MASK_SECRET))
    )


def build_job_consumer(
    *,
    job_queue: asyncio.Queue[ExecutionJobMessage],
    result_queue: asyncio.Queue[ExecutionResultMessage],
) -> JobConsumer:
    credentials = MinioStorageCredentials(
        host=settings.STORAGE_ENDPOINT,
        access_key=settings.STORAGE_ACCESS_KEY,
        secret_key=settings.STORAGE_SECRET_KEY,
        bucket=settings.STORAGE_BUCKET,
    )
    orchestrator = ExecutionOrchestrator(
        build_pipeline(credentials),
        credentials=credentials,
        result_sink=QueueResultSink(result_queue),
    )
    return JobConsumer(
        QueueJobSource(job_queue), orchestrator, concurrency=settings.WORKER_CONCURRENCY
    )
