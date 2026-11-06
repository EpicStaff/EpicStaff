"""Reads the execution's result or failure file and finalizes the outcome.

The launch step leaves raw streams and a return code on the context. This step reads
the result file on a clean exit (a non-zero or timed-out run never finished writing it)
and marks the context complete -- the last step in every run. A result file the child
replaced with a symlink, a FIFO or an oversized file fails the run, and so does a result
file the wrapped code couldn't write. Secret scrubbing is not done here: the orchestrator
masks stdout/stderr/result/failure on the way out, so an earlier step that fails after
the output is captured cannot bypass it.

A run that exited non-zero gets the failure the wrapped code wrote before it exited. The
user's code runs in that same process and can write the file too, so only a failure the
wrapper itself can report is believed: anything else, including a claim that the
sandbox failed, counts as the code exiting on its own.
"""

import signal

from loguru import logger
from src.shared.models.code_failure import (
    WRAPPER_FAILURE_CODES,
    CodeFailure,
    CodeFailureCode,
)

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
# The wrapper caps the texts it puts in the failure file well below this.
_MAX_FAILURE_FILE_BYTES = 128 * 1024
# A process killed by a signal reports minus the signal's number. Linux numbers, written
# out because the signal module only names the host's own signals.
# SIGKILL: in a run that didn't time out, most often the kernel's OOM killer.
_KILLED_RETURNCODE = -9
_KILLED_MESSAGE = (
    "The code was stopped before it returned a result, most likely because it used too much memory."
)
# SIGILL, SIGABRT, SIGBUS, SIGFPE, SIGSEGV: the process crashed, which pure Python code
# can't do, so the crash is in native code a library brought.
_CRASH_RETURNCODES = frozenset({-4, -6, -7, -8, -11})
_CRASHED_MESSAGE = (
    "The code crashed before it returned a result, most likely inside a library it uses."
)
_STOPPED_BY_SIGNAL_MESSAGE = (
    "The code was stopped by the system before it returned a result ({signal_name})."
)
_EXITED_MESSAGE = (
    "The code exited with code {returncode} before it returned a result. Its error output "
    "may say why."
)


class CaptureResultStep:
    def __init__(self, *, max_bytes: int):
        self._max_bytes = max_bytes

    async def __call__(self, context: ExecutionContext) -> None:
        marker = _result_write_failure_marker(context)
        if marker is not None:
            _fail_on_unwritten_result_file(context, marker)
            return

        # The launch step already recorded why the run ended: it timed out.
        if context.failure is not None:
            context.complete()
            return

        if context.returncode != 0:
            _capture_failure(context)
            context.complete()
            return

        if context.result_file_path is not None:
            try:
                context.result_data = read_control_file(
                    context.result_file_path, max_bytes=self._max_bytes
                )
            except ControlFileTooLargeError as error:
                logger.warning("Rejected result file of {}: {}", context.job.execution_id, error)
                context.fail(
                    CodeFailure(
                        code=CodeFailureCode.RESULT_TOO_LARGE, detail=_RESULT_TOO_LARGE_MESSAGE
                    )
                )
                return
            except UnsafeControlFileError as error:
                fail_on_sandbox_error(context, f"Rejected the result file: {error}.")
                return
            except Exception:
                logger.exception("Exception reading result file")

        context.complete()


def _capture_failure(context: ExecutionContext) -> None:
    """Take the failure the wrapped code reported, or record that the code exited on its own.

    The wrapper wrote its failure's detail to stderr itself, so an accepted failure is
    taken as it is; only the fallback adds a line.
    """
    failure = _read_wrapper_failure(context)
    if failure is not None:
        context.failure = failure
        return
    context.record_failure(
        CodeFailure(
            code=CodeFailureCode.CODE_EXITED, detail=_code_exited_detail(context.returncode)
        )
    )


def _read_wrapper_failure(context: ExecutionContext) -> CodeFailure | None:
    execution_id = context.job.execution_id
    if context.failure_file_path is None:
        return None
    try:
        text = read_control_file(context.failure_file_path, max_bytes=_MAX_FAILURE_FILE_BYTES)
        failure = None if text is None else CodeFailure.model_validate_json(text)
    except (UnsafeControlFileError, OSError, ValueError) as error:
        # The type only: a validation error quotes the file, which the user's code can fill.
        logger.warning(
            "Ignored the failure file of execution {}: {}", execution_id, type(error).__name__
        )
        return None
    if failure is None:
        logger.warning(
            "Execution {} exited {} without a failure file", execution_id, context.returncode
        )
        return None
    if failure.code not in WRAPPER_FAILURE_CODES:
        logger.warning(
            "Ignored the failure file of execution {}: it claims {}, which the wrapped code "
            "can't report",
            execution_id,
            failure.code.value,
        )
        return None
    return failure


def _code_exited_detail(returncode: int) -> str:
    if returncode == _KILLED_RETURNCODE:
        return _KILLED_MESSAGE
    if returncode in _CRASH_RETURNCODES:
        return _CRASHED_MESSAGE
    if returncode < 0:
        return _STOPPED_BY_SIGNAL_MESSAGE.format(signal_name=_signal_name(-returncode))
    return _EXITED_MESSAGE.format(returncode=returncode)


def _signal_name(number: int) -> str:
    try:
        return signal.Signals(number).name
    except ValueError:
        return f"signal {number}"


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
