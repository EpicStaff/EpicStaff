"""The mutable working state threaded through one execution's pipeline.

Each step reads what earlier steps put here and writes what later steps need. It
also carries the outcome: once the pipeline finishes, the orchestrator reads
``returncode``/``stdout``/``stderr``/``result_data``/``error`` off the context to build
the wire result. Errors are recorded here via ``fail`` rather than raised, so a failing
step ends the run cleanly instead of taking the worker down.
"""

from pathlib import Path
from typing import Literal

from foundation.schemas import ErrorDetailSchema
from pydantic import BaseModel, ConfigDict

from worker.domain.models import IsolationPlan, Job, StorageMutations

__all__ = ["UNSAFE_TO_RUN_MESSAGE", "ExecutionContext", "RunFailureCode"]

# Failed with when the isolation a run needs is missing or could not be set up. Which
# isolation, and how to change that, is the operator's business and goes to the log.
UNSAFE_TO_RUN_MESSAGE = "This server can't run code safely right now, so the code wasn't run."

# Why the sandbox failed a run itself; the ``code`` of the result's error. Stable: a
# producer may tell failures apart by it, so a value is never renamed.
type RunFailureCode = Literal[
    "server_error",
    "isolation_unavailable",
    "storage_scope_missing",
    "venv_missing",
    "unsafe_control_file",
    "result_too_large",
    "result_undeliverable",
]


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

    # The isolation decisions for this run; set by the build-isolation-plan step.
    isolation: IsolationPlan | None = None

    # The environment handed to the child interpreter.
    env: dict[str, str] = {}
    # Values scrubbed from the output even when MASK_SECRET is off -- worker-issued
    # credentials the code author never chose to see, unlike the job's user secrets.
    # Register through mask_always(), in the step that hands the value to the child.
    # Values only: a user secret may share an env-var name with one of these, and
    # both values must be masked.
    always_masked: set[str] = set()
    # Storage changes the execution reported; published by the orchestrator.
    storage_mutations: StorageMutations | None = None

    # The outcome, filled as the run progresses.
    returncode: int | None = None
    stdout: str = ""
    stderr: str = ""
    result_data: str | None = None
    # Set when the sandbox failed the run itself; stderr keeps only the child's output.
    error: ErrorDetailSchema | None = None
    # Set once the run has reached a terminal state; the pipeline stops here.
    completed: bool = False

    model_config = ConfigDict(validate_assignment=True)

    def mask_always(self, value: str) -> None:
        """Have the orchestrator scrub `value` from the output, whatever MASK_SECRET says.

        An empty value is skipped: there is nothing to leak, and masking it would match
        nowhere anyway.
        """
        if value:
            self.always_masked.add(value)

    def complete(self) -> None:
        """Mark the run finished with whatever outcome fields are already set."""
        self.completed = True

    def fail(self, code: RunFailureCode, message: str, returncode: int = 1) -> None:
        """Record a failure of the sandbox as the run's error and mark the run finished.

        Whatever the child already wrote to stderr stays there, unchanged.

        Args:
            code: The error's code, naming why the run failed.
            message: The error's detail, shown to the user. A fixed text, never one
                built from an exception.
        """
        self.error = ErrorDetailSchema(code=code, detail=message)
        self.returncode = returncode
        self.completed = True
