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

from worker.application.context import ExecutionContext, fail_on_sandbox_error
from worker.infrastructure.execution.code_wrapper import RESULT_WRITE_FAILED_EXIT_CODE
from worker.infrastructure.execution.control_files import (
    ControlFileTooLargeError,
    UnsafeControlFileError,
    read_control_file,
)

__all__ = ["CaptureResultStep"]

# The limit is left out: the text would have to repeat how an administrator spelled
# SANDBOX_MAX_RESULT_SIZE, and drift from it when the setting's format changes.
_RESULT_TOO_LARGE_MESSAGE = "The function's return value is too big to save. Return less data."
# A real write error is short. User code can still write past the marker (an atexit
# handler, or code that read the marker out of its own process), so the log is capped.
_MAX_LOGGED_WRITE_ERROR_LENGTH = 500


class CaptureResultStep:
    def __init__(self, *, max_bytes: int):
        self._max_bytes = max_bytes

    async def __call__(self, context: ExecutionContext) -> None:
        marker = _result_write_failure_marker(context)
        if marker is not None:
            _fail_on_unwritten_result_file(context, marker)
            return

        if context.returncode == 0 and context.result_file_path is not None:
            try:
                context.result_data = read_control_file(
                    context.result_file_path, max_bytes=self._max_bytes
                )
            except ControlFileTooLargeError as error:
                logger.warning("Rejected result file of {}: {}", context.job.execution_id, error)
                context.fail(_RESULT_TOO_LARGE_MESSAGE)
                return
            except UnsafeControlFileError as error:
                fail_on_sandbox_error(context, f"Rejected the result file: {error}.")
                return
            except Exception:
                logger.exception("Exception reading result file")

        context.complete()


def _result_write_failure_marker(context: ExecutionContext) -> str | None:
    """Return the run's marker if the wrapped code reported a result-file write failure."""
    if context.returncode != RESULT_WRITE_FAILED_EXIT_CODE:
        return None
    marker = context.result_write_marker
    if not marker:
        logger.debug(
            "Execution {} exited {} but has no result-write marker; treated as an ordinary exit",
            context.job.execution_id,
            RESULT_WRITE_FAILED_EXIT_CODE,
        )
        return None
    if marker not in context.stderr:
        logger.debug(
            "Execution {} exited {} without its result-write marker on stderr, so the "
            "user's code exited with it",
            context.job.execution_id,
            RESULT_WRITE_FAILED_EXIT_CODE,
        )
        return None
    return marker


def _fail_on_unwritten_result_file(context: ExecutionContext, marker: str) -> None:
    # Everything after the last marker is the write error, naming the server's result
    # path; whatever the user's code wrote before it stays theirs, even an echo of the
    # marker.
    marker_index = context.stderr.rindex(marker)
    write_error = context.stderr[marker_index + len(marker) :].rstrip("\n")
    context.stderr = context.stderr[:marker_index].rstrip("\n")
    write_error = write_error[:_MAX_LOGGED_WRITE_ERROR_LENGTH]
    # A real write error is one line. repr keeps anything else on one log line, so text
    # written past the marker can't pass itself off as separate log entries.
    fail_on_sandbox_error(
        context, f"The wrapped code couldn't write the result file: {write_error!r}"
    )
