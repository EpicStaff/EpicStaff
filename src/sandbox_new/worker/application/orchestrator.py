"""Runs one job end to end and hands the outcome back to the manager.

Owns the lifecycle the pipeline steps must not: whatever the run does, scoped
storage credentials are revoked and the per-execution directory is removed, then the
result (and any captured mutations) are sent back. The pipeline never raises -- a
failed run lands in the context -- so a result is always produced and sent.
"""

import asyncio
import shutil

from loguru import logger

from worker.application.context import ExecutionContext
from worker.application.pipeline import Pipeline
from worker.application.ports.result_sink import AbstractResultSink
from worker.application.ports.storage_credentials import AbstractStorageCredentials
from worker.domain.models import ExecutionResult, Job

__all__ = ["ExecutionOrchestrator"]


class ExecutionOrchestrator:
    def __init__(
        self,
        pipeline: Pipeline,
        *,
        credentials: AbstractStorageCredentials,
        result_sink: AbstractResultSink,
    ):
        self._pipeline = pipeline
        self._credentials = credentials
        self._result_sink = result_sink

    async def execute(self, job: Job) -> None:
        context = ExecutionContext(job=job)
        try:
            await self._pipeline.run(context)
        finally:
            await self._finalize(context)

        result = ExecutionResult(
            execution_id=job.execution_id,
            result=context.result_data,
            stdout=context.stdout,
            stderr=context.stderr,
            returncode=context.returncode if context.returncode is not None else 1,
        )
        await self._result_sink.send(result, mutations=context.storage_mutations)

    async def _finalize(self, context: ExecutionContext) -> None:
        if context.storage_credentials is not None:
            try:
                await self._credentials.revoke(context.storage_credentials.access_key)
            except Exception:
                logger.exception(
                    "Failed to revoke storage credentials for {}", context.job.execution_id
                )

        if context.exec_dir is not None:
            try:
                await asyncio.to_thread(shutil.rmtree, context.exec_dir)
            except Exception as error:
                logger.warning("Failed to clean up {}: {}", context.exec_dir, error)
