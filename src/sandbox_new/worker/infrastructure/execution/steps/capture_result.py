"""Reads the execution's result file and finalizes the outcome.

The launch step leaves raw streams and a return code on the context. This step
reads the result file on a clean exit (a non-zero or timed-out run never finished
writing it) and marks the context complete -- the last step in every run. Secret
scrubbing is not done here: the orchestrator masks stdout/stderr/result on the way
out, so an earlier step that fails after the output is captured cannot bypass it.
"""

from loguru import logger

from worker.application.context import ExecutionContext

__all__ = ["CaptureResultStep"]


class CaptureResultStep:
    async def __call__(self, context: ExecutionContext) -> None:
        if context.returncode == 0 and context.result_file_path is not None:
            try:
                context.result_data = context.result_file_path.read_text(encoding="utf-8")
            except Exception:
                logger.exception("Exception reading result file")

        context.complete()
