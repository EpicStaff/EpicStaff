"""The mutable working state threaded through one execution's pipeline.

Each step reads what earlier steps put here and writes what later steps need. It
also carries the outcome: once the pipeline finishes, the orchestrator reads
``returncode``/``stdout``/``stderr``/``result_data`` off the context to build the
wire result. Errors are recorded here via ``fail`` rather than raised, so a failing
step ends the run cleanly instead of taking the worker down.
"""

import traceback
from pathlib import Path

from common.public_errors import SandboxFailureMessage, report_sandbox_failure
from pydantic import BaseModel, ConfigDict

from worker.application.secret_scrubber import scrub
from worker.domain.models import IsolationPlan, Job, StorageMutations

__all__ = ["ExecutionContext"]


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
    # Set once the run has reached a terminal state; the pipeline stops here.
    completed: bool = False

    model_config = ConfigDict(validate_assignment=True)

    def complete(self) -> None:
        """Mark the run finished with whatever outcome fields are already set."""
        self.completed = True

    def fail(self, error: Exception | str, returncode: int = 1) -> None:
        """Record a failure as the run's outcome and mark it finished."""
        message = str(error)
        self.stderr = f"{self.stderr}\n{message}" if self.stderr else message
        self.returncode = returncode
        self.completed = True

    def fail_on_sandbox_error(
        self,
        detail: Exception | str,
        *,
        public_message: SandboxFailureMessage = SandboxFailureMessage.SERVER_ERROR,
    ) -> None:
        """Fail the run on the sandbox's own error, not the user's code.

        ``detail`` can name server settings or quote raw exception text, so it is only
        logged, under a fresh reference; the user sees ``public_message`` citing it.
        An exception is logged with its traceback. Either way the job's secret values
        are masked first, since an exception's text can quote them.
        """
        if isinstance(detail, BaseException):
            detail = "".join(traceback.format_exception(detail)).rstrip("\n")
        logged_detail = scrub(text=detail, secrets=self.job.secrets or {})
        self.fail(
            report_sandbox_failure(
                public_message, logged_detail, execution_id=self.job.execution_id
            )
        )
