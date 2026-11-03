"""Reads the execution's result file and finalizes the outcome.

The launch step leaves raw streams and a return code on the context. This step
reads the result file on a clean exit (a non-zero or timed-out run never finished
writing it) and marks the context complete -- the last step in every run. A result
file the child replaced with a symlink, a FIFO or an oversized file fails the run, and
so does a result file the wrapped code couldn't write. Secret scrubbing is not done
here: the orchestrator masks stdout/stderr/result on the way out, so an earlier step
that fails after the output is captured cannot bypass it.
"""

from loguru import logger

from worker.application.context import ExecutionContext
from worker.infrastructure.execution.code_wrapper import RESULT_WRITE_FAILED_EXIT_CODE
from worker.infrastructure.execution.control_files import (
    ControlFileTooLargeError,
    UnsafeControlFileError,
    read_control_file,
)

__all__ = ["CaptureResultStep"]

_RESULT_TOO_LARGE_MESSAGE = (
    "The function's return value is too big to save (over {size}). Return less data."
)
_SIZE_UNITS = (("MB", 1024 * 1024), ("KB", 1024))
# A real OS error line is short; anything longer came from user code faking the exit code.
_MAX_LOGGED_WRITE_ERROR_LENGTH = 500


class CaptureResultStep:
    def __init__(self, *, max_bytes: int):
        self._max_bytes = max_bytes

    async def __call__(self, context: ExecutionContext) -> None:
        if context.returncode == RESULT_WRITE_FAILED_EXIT_CODE:
            _fail_on_unwritten_result_file(context)
            return

        if context.returncode == 0 and context.result_file_path is not None:
            try:
                context.result_data = read_control_file(
                    context.result_file_path, max_bytes=self._max_bytes
                )
            except ControlFileTooLargeError as error:
                logger.warning("Rejected result file of {}: {}", context.job.execution_id, error)
                context.fail(_RESULT_TOO_LARGE_MESSAGE.format(size=_format_size(error.max_bytes)))
                return
            except UnsafeControlFileError as error:
                context.fail_on_sandbox_error(f"Rejected the result file: {error}.")
                return
            except Exception:
                logger.exception("Exception reading result file")

        context.complete()


def _fail_on_unwritten_result_file(context: ExecutionContext) -> None:
    # The wrapped code's last stderr line is the write error, naming the server's
    # result path; whatever the user's code wrote before it stays theirs.
    user_stderr, _, write_error = context.stderr.rstrip("\n").rpartition("\n")
    context.stderr = user_stderr.rstrip("\n")
    # User code can fake this exit code, so the line it hands over may be anything.
    write_error = write_error[:_MAX_LOGGED_WRITE_ERROR_LENGTH]
    context.fail_on_sandbox_error(f"The wrapped code couldn't write the result file: {write_error}")


def _format_size(size_bytes: int) -> str:
    """Name a size in the largest unit it reaches, the way the size settings spell it.

    One decimal at most, dropped when it is zero: 16777216 bytes is "16 MB". The units
    are binary, matching how ``SANDBOX_MAX_RESULT_SIZE`` reads "16mb".
    """
    for unit, unit_bytes in _SIZE_UNITS:
        if size_bytes >= unit_bytes:
            return f"{size_bytes / unit_bytes:.1f}".removesuffix(".0") + f" {unit}"
    return f"{size_bytes} bytes"
