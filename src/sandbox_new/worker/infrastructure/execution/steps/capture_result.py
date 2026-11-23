"""Reads the execution's result file and finalizes the outcome.

The launch step leaves raw streams and a return code on the context. This step
reads the result file on a clean exit (a non-zero or timed-out run never finished
writing it) and marks the context complete -- the last step in every run. A result
file the child replaced with a symlink, a FIFO or an oversized file fails the run. Secret
scrubbing is not done here: the orchestrator masks stdout/stderr/result on the way
out, so an earlier step that fails after the output is captured cannot bypass it.
"""

from loguru import logger
from src.shared.sandbox_errors import SANDBOX_SERVER_ERROR_MESSAGE

from worker.application.context import ExecutionContext
from worker.infrastructure.execution.control_files import (
    ControlFileTooLargeError,
    UnsafeControlFileError,
    read_control_file,
)

__all__ = ["CaptureResultStep"]

_RESULT_TOO_LARGE = "The function's return value is too big to save."


class CaptureResultStep:
    def __init__(self, *, max_bytes: int):
        self._max_bytes = max_bytes

    async def __call__(self, context: ExecutionContext) -> None:
        if context.returncode == 0 and context.result_file_path is not None:
            try:
                context.result_data = read_control_file(
                    context.result_file_path, max_bytes=self._max_bytes
                )
            except ControlFileTooLargeError as error:
                logger.warning("Rejected result file of {}: {}", context.job.execution_id, error)
                context.fail("result_too_large", _RESULT_TOO_LARGE)
                return
            except UnsafeControlFileError as error:
                logger.error("Rejected result file of {}: {}", context.job.execution_id, error)
                context.fail("unsafe_control_file", SANDBOX_SERVER_ERROR_MESSAGE)
                return
            except Exception:
                logger.exception("Exception reading result file")

        context.complete()
