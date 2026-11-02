"""Assembles the worker runtime from settings and the shared queues.

The composition root for the worker: it wires the execution pipeline (every step in
order), the queue source/sink, the admission gate and the job consumer. The pipeline is
stateless and reused across jobs -- per-job state lives in the context.
"""

import asyncio

import settings
from common.contracts import ExecutionJobMessage, ExecutionResultMessage

from worker.application.orchestrator import ExecutionOrchestrator
from worker.application.pipeline import Pipeline
from worker.application.ports import AbstractAdmissionGate
from worker.application.resource_gate import ResourceAdmissionGate
from worker.application.steps import BuildIsolationPlan, ConfigureStorageStep
from worker.infrastructure.admission import HostMetrics
from worker.infrastructure.execution.steps import (
    CaptureMutationsStep,
    CaptureResultStep,
    LaunchStep,
    PrepareWorkspaceStep,
    ResolveVenvStep,
    WrapCodeStep,
)
from worker.infrastructure.isolation.probe import LandlockIsolationProbe
from worker.infrastructure.transport.queue_job_source import QueueJobSource
from worker.infrastructure.transport.queue_result_sink import QueueResultSink
from worker.presentation.job_consumer import JobConsumer

__all__ = ["build_admission_gate", "build_job_consumer", "build_pipeline"]


def build_pipeline() -> Pipeline:
    return (
        Pipeline()
        .register(ResolveVenvStep(venvs_dir=settings.VENVS_DIR))
        .register(PrepareWorkspaceStep(executions_dir=settings.EXECUTIONS_DIR))
        .register(
            ConfigureStorageStep(
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
        .register(
            LaunchStep(
                default_timeout=settings.DEFAULT_EXECUTION_TIMEOUT,
                min_timeout=settings.MIN_EXECUTION_TIMEOUT,
                max_timeout=settings.MAX_EXECUTION_TIMEOUT,
            )
        )
        .register(CaptureMutationsStep(max_bytes=settings.MAX_RESULT_SIZE))
        .register(CaptureResultStep(max_bytes=settings.MAX_RESULT_SIZE))
    )


def build_admission_gate() -> ResourceAdmissionGate:
    return ResourceAdmissionGate(
        HostMetrics(),
        min_concurrent=settings.MIN_CONCURRENT_EXECUTIONS,
        max_concurrent=settings.MAX_CONCURRENT_EXECUTIONS,
        cpu_threshold=settings.CPU_ADMIT_THRESHOLD,
        memory_threshold=settings.MEMORY_ADMIT_THRESHOLD,
    )


def build_job_consumer(
    *,
    job_queue: asyncio.Queue[ExecutionJobMessage],
    result_queue: asyncio.Queue[ExecutionResultMessage],
    gate: AbstractAdmissionGate,
) -> JobConsumer:
    orchestrator = ExecutionOrchestrator(
        build_pipeline(),
        result_sink=QueueResultSink(result_queue),
        mask_secrets=settings.MASK_SECRET,
    )
    return JobConsumer(
        QueueJobSource(job_queue), orchestrator, gate, queue_timeout=settings.QUEUE_TIMEOUT
    )
