"""Runs one job end to end and hands the outcome back to the manager.

Owns the lifecycle the pipeline steps must not: whatever the run does, the
per-execution directory is removed and the result (and any captured mutations) are
sent back. Storage credentials are not revoked here -- they are issued and revoked
by django_app, which owns them. The pipeline never raises -- a failed run lands in
the context -- so a result is always produced and sent.
"""

import asyncio
import shutil
from collections.abc import Callable

from loguru import logger
from src.shared.bench_log import BENCH_LEVEL
from src.shared.models.code_failure import CodeFailure

from worker.application.context import ExecutionContext
from worker.application.pipeline import Pipeline
from worker.application.ports.result_sink import AbstractResultSink
from worker.application.secret_scrubber import scrub
from worker.domain.models import ExecutionResult, Job

__all__ = ["ExecutionOrchestrator"]

# How much of a failure's free text (its detail, an exception's message) and of a name
# in it (an exception type, an argument) a user is shown.
_MAX_SHOWN_TEXT_LENGTH = 4000
_MAX_SHOWN_NAME_LENGTH = 200


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
        logger.log(
            BENCH_LEVEL,
            "bench {checkpoint}",
            checkpoint="exec_end",
            session_id=job.session_id,
            execution_id=job.execution_id,
            returncode=result.returncode,
        )
        await self._result_sink.send(result, mutations=context.storage_mutations)

    async def fail(
        self,
        execution_id: str,
        failure: CodeFailure,
        *,
        reference: str | None = None,
        session_id: int | None,
        reply_to_crew_channel: bool,
    ) -> None:
        """Send a failed result for a job without running it.

        Used when the job cannot or must not run -- it expired in the queue, or the
        worker failed around it -- so its producer still gets an outcome. The result is
        marked as not run, so it does not count as a completed execution.

        Args:
            failure: Its detail is shown to the user as the run's stderr: a fixed text,
                never one built from an exception, which could quote the job's secrets.
            reference: The reference of the log line that explains the failure, if any.
            session_id: The job's session, when known; names it in the manager's BENCH
                checkpoint.
            reply_to_crew_channel: Echoed from the job, so the result goes to the
                channel its producer listens on.
        """
        await self._result_sink.send(
            ExecutionResult(
                execution_id=execution_id,
                stderr=failure.detail,
                returncode=1,
                reply_to_crew_channel=reply_to_crew_channel,
                ran=False,
                session_id=session_id,
                failure=failure,
                reference=reference,
            )
        )

    def _build_result(self, context: ExecutionContext) -> ExecutionResult:
        # The scrub runs here, not in a pipeline step, so it covers every outcome --
        # including a step that failed after the child's output was captured, where
        # the pipeline stops before the capture step would have masked anything.
        stdout = context.stdout
        stderr = context.stderr
        result_data = context.result_data
        failure = context.failure
        if self._mask_secrets:
            secrets = context.job.secrets or {}
            stdout = scrub(text=stdout, secrets=secrets) or ""
            stderr = scrub(text=stderr, secrets=secrets) or ""
            result_data = scrub(text=result_data, secrets=secrets)
            if failure is not None:
                failure = _scrub_failure(failure, secrets)
        # Shortened only after the scrub: a cut through a secret would leave a prefix the
        # scrub no longer recognises. Stderr is not shortened; it is the run's output.
        if failure is not None:
            failure = _shorten_failure(failure)
        return ExecutionResult(
            execution_id=context.job.execution_id,
            result=result_data,
            stdout=stdout,
            stderr=stderr,
            returncode=context.returncode if context.returncode is not None else 1,
            reply_to_crew_channel=context.job.reply_to_crew_channel,
            ran=True,
            session_id=context.job.session_id,
            failure=failure,
            reference=context.reference,
        )

    async def _finalize(self, context: ExecutionContext) -> None:
        if context.exec_dir is not None:
            try:
                await asyncio.to_thread(shutil.rmtree, context.exec_dir)
            except Exception as error:
                logger.warning("Failed to clean up {}: {}", context.exec_dir, error)


def _scrub_failure(failure: CodeFailure, secrets: dict[str, str]) -> CodeFailure:
    """Mask the job's secrets in every part of ``failure`` the user's code can put text in.

    The detail repeats the user's exception message, the same text stderr carries.
    """
    return _map_failure_texts(
        failure,
        text=lambda value: scrub(text=value, secrets=secrets),
        name=lambda value: scrub(text=value, secrets=secrets),
    )


def _shorten_failure(failure: CodeFailure) -> CodeFailure:
    """Cut the texts of ``failure`` the user's code controls to what a message can show."""
    return _map_failure_texts(
        failure,
        text=lambda value: _shortened(value, _MAX_SHOWN_TEXT_LENGTH),
        name=lambda value: _shortened(value, _MAX_SHOWN_NAME_LENGTH),
    )


def _map_failure_texts(
    failure: CodeFailure,
    *,
    text: Callable[[str], str],
    name: Callable[[str], str],
) -> CodeFailure:
    """Apply ``text`` to the free texts of ``failure`` and ``name`` to its names."""
    changes: dict[str, object] = {
        "detail": text(failure.detail),
        "attr": None if failure.attr is None else name(failure.attr),
    }
    if failure.user_error is not None:
        changes["user_error"] = failure.user_error.model_copy(
            update={
                "exception_type": name(failure.user_error.exception_type),
                "message": text(failure.user_error.message),
            }
        )
    return failure.model_copy(update=changes)


def _shortened(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[:limit] + "..."
