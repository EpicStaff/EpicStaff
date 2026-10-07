"""Reads the execution's result file, scrubs secrets, and finalizes the outcome.

The launch step leaves raw streams and a return code on the context. This step
scrubs the streams, reads the result file on a clean exit (a non-zero or timed-out
run never finished writing it), scrubs that too, and marks the context complete --
the last step in every run.
"""

from loguru import logger

from worker.application.context import ExecutionContext
from worker.infrastructure.secret_scrubber import scrub

__all__ = ["CaptureResultStep"]


class CaptureResultStep:
    def __init__(self, *, mask_secrets: bool):
        self._mask_secrets = mask_secrets

    async def __call__(self, context: ExecutionContext) -> None:
        secrets = context.job.secrets or {}

        if self._mask_secrets:
            context.stdout = scrub(text=context.stdout, secrets=secrets) or ""
            context.stderr = scrub(text=context.stderr, secrets=secrets) or ""

        if context.returncode == 0 and context.result_file_path is not None:
            try:
                raw_result = context.result_file_path.read_text(encoding="utf-8")
            except Exception:
                logger.exception("Exception reading result file")
            else:
                context.result_data = (
                    scrub(text=raw_result, secrets=secrets) if self._mask_secrets else raw_result
                )

        context.complete()
