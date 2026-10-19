"""Runs one job end to end and hands the outcome back to the manager.

Owns the lifecycle the pipeline steps must not: whatever the run does, the
per-execution directory is removed and the result (and any captured mutations) are
sent back. Storage credentials are not revoked here -- they are issued and revoked
by django_app, which owns them. The pipeline never raises -- a failed run lands in
the context -- so a result is always produced and sent.
"""

import asyncio
import shutil

from loguru import logger

from worker.application.context import ExecutionContext
from worker.application.pipeline import Pipeline
from worker.application.ports.result_sink import AbstractResultSink
from worker.application.secret_scrubber import scrub
from worker.domain.models import ExecutionResult, Job

__all__ = ["ExecutionOrchestrator"]


class ExecutionOrchestrator:
    def __init__(
        self,
        pipeline: Pipeline,
        *,
        result_sink: AbstractResultSink,
        mask_secrets: bool,
    ):
        self._pipeline = pipeline
        self._result_sink = result_sink
        self._mask_secrets = mask_secrets

    async def execute(self, job: Job) -> None:
        context = ExecutionContext(job=job)
        try:
            await self._pipeline.run(context)
        finally:
            await self._finalize(context)

        result = self._build_result(context)
        await self._result_sink.send(result, mutations=context.storage_mutations)

    def _build_result(self, context: ExecutionContext) -> ExecutionResult:
        # The scrub runs here, not in a pipeline step, so it covers every outcome --
        # including a step that failed after the child's output was captured, where
        # the pipeline stops before the capture step would have masked anything.
        stdout = context.stdout
        stderr = context.stderr
        result_data = context.result_data
        if self._mask_secrets:
            secrets = context.job.secrets or {}
            stdout = scrub(text=stdout, secrets=secrets) or ""
            stderr = scrub(text=stderr, secrets=secrets) or ""
            result_data = scrub(text=result_data, secrets=secrets)
        return ExecutionResult(
            execution_id=context.job.execution_id,
            result=result_data,
            stdout=stdout,
            stderr=stderr,
            returncode=context.returncode if context.returncode is not None else 1,
        )

    async def _finalize(self, context: ExecutionContext) -> None:
        if context.exec_dir is not None:
            try:
                await asyncio.to_thread(shutil.rmtree, context.exec_dir)
            except Exception as error:
                logger.warning("Failed to clean up {}: {}", context.exec_dir, error)
