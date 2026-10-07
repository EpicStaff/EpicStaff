"""The mutable working state threaded through one execution's pipeline.

Each step reads what earlier steps put here and writes what later steps need. It
also carries the outcome: once the pipeline finishes, the presentation layer reads
``returncode``/``stdout``/``stderr``/``result_data`` off the context to build the
wire result. Errors are recorded here via ``fail`` rather than raised, so a failing
step ends the run cleanly instead of taking the worker down.
"""

from pathlib import Path

from pydantic import BaseModel, ConfigDict

from worker.domain.models import IsolationPlan, Job, StorageCredentials, StorageMutations

__all__ = ["ExecutionContext"]


class ExecutionContext(BaseModel):
    job: Job

    # Resolved by the venv and workspace steps.
    python_executable: Path | None = None
    exec_dir: Path | None = None
    home_dir: Path | None = None
    tmp_dir: Path | None = None
    savefiles_root: Path | None = None
    code_path: Path | None = None
    result_file_path: Path | None = None
    storage_mutations_path: Path | None = None

    # The isolation decisions for this run; set by the build-isolation-plan step.
    isolation: IsolationPlan | None = None

    # The environment handed to the child interpreter.
    env: dict[str, str] = {}
    # Scoped storage credentials provisioned for this execution; transient.
    storage_credentials: StorageCredentials | None = None
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
