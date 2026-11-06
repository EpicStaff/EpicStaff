"""The mutable working state threaded through one execution's pipeline.

Each step reads what earlier steps put here and writes what later steps need. It
also carries the outcome: once the pipeline finishes, the orchestrator reads
``returncode``/``stdout``/``stderr``/``result_data``/``failure`` off the context to
build the wire result. Errors are recorded here via ``fail`` rather than raised, so a
failing step ends the run cleanly instead of taking the worker down.

``fail_on_sandbox_error`` sits beside the model rather than on it, so the model stays a
state carrier. It lives in this module because pipeline steps in ``worker.infrastructure``
call it, and the import contracts let them reach the application layer only through its
ports and this module.
"""

import traceback
from pathlib import Path

from common.public_errors import log_sandbox_failure, sandbox_failure
from pydantic import BaseModel, ConfigDict
from src.shared.models.code_failure import CodeFailure, CodeFailureCode

from worker.application.secret_scrubber import scrub
from worker.domain.models import IsolationPlan, Job, StorageMutations

__all__ = ["ExecutionContext", "fail_on_sandbox_error"]


class ExecutionContext(BaseModel):
    job: Job

    # Resolved by the venv and workspace steps.
    python_executable: Path | None = None
    exec_dir: Path | None = None
    home_dir: Path | None = None
    tmp_dir: Path | None = None
    work_dir: Path | None = None
    code_path: Path | None = None
    result_file_path: Path | None = None
    # The wrapped code writes why it failed here, before it exits non-zero.
    failure_file_path: Path | None = None
    storage_mutations_path: Path | None = None
    # Set by the wrap step: the wrapped code writes it before a result-file write error.
    result_write_marker: str | None = None

    # The isolation decisions for this run; set by the build-isolation-plan step.
    isolation: IsolationPlan | None = None

    # The environment handed to the child interpreter.
    env: dict[str, str] = {}
    # Storage changes the execution reported; published by the orchestrator.
    storage_mutations: StorageMutations | None = None

    # The outcome, filled as the run progresses.
    returncode: int | None = None
    stdout: str = ""
    stderr: str = ""
    result_data: str | None = None
    # Why the run failed, and the reference of the log line that explains it, if any.
    failure: CodeFailure | None = None
    reference: str | None = None
    # Set once the run has reached a terminal state; the pipeline stops here.
    completed: bool = False

    model_config = ConfigDict(validate_assignment=True)

    def complete(self) -> None:
        """Mark the run finished with whatever outcome fields are already set."""
        self.completed = True

    def record_failure(self, failure: CodeFailure, *, reference: str | None = None) -> None:
        """Record why the run failed and add ``failure.detail`` as the last line of stderr.

        The run is not finished by this: a later step still decides the outcome.
        """
        self.failure = failure
        self.reference = reference
        self.stderr = f"{self.stderr}\n{failure.detail}" if self.stderr else failure.detail

    def fail(
        self, failure: CodeFailure, *, reference: str | None = None, returncode: int = 1
    ) -> None:
        """Record a failure as the run's outcome and mark it finished."""
        self.record_failure(failure, reference=reference)
        self.returncode = returncode
        self.completed = True


def fail_on_sandbox_error(
    context: ExecutionContext,
    detail: Exception | str,
    *,
    code: CodeFailureCode = CodeFailureCode.SANDBOX_ERROR,
) -> None:
    """Fail the run on the sandbox's own error, not the user's code.

    ``detail`` can name server settings or quote raw exception text, so it is only
    logged, under a fresh reference; the user sees the fixed text for ``code`` citing
    it, and the run carries the reference. An exception is logged with its traceback.
    Either way the job's secret values are masked first, since an exception's text can
    quote them.

    Args:
        code: ``sandbox_error``, or ``unsafe_to_run`` when the server can't isolate the
            code safely.
    """
    if isinstance(detail, BaseException):
        detail = "".join(traceback.format_exception(detail)).rstrip("\n")
    logged_detail = scrub(text=detail, secrets=context.job.secrets or {})
    reference = log_sandbox_failure(logged_detail, execution_id=context.job.execution_id)
    context.fail(sandbox_failure(code, reference), reference=reference)
