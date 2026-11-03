"""Resolves the venv the job names to a python binary on the shared volume.

The manager builds venvs and only dispatches a job once its venv is COMPLETED, so the
wait lives there, not here. This step derives the path from the hash and checks the
binary exists -- defense in depth, not a substitute for the manager's gate: if the
venv is missing it fails the job rather than launching against a bad path.
"""

from pathlib import Path

from worker.application.context import ExecutionContext

__all__ = ["ResolveVenvStep"]


class ResolveVenvStep:
    def __init__(self, *, venvs_dir: Path):
        self._venvs_dir = venvs_dir

    async def __call__(self, context: ExecutionContext) -> None:
        venv_hash = context.job.venv_hash
        venv_path = self._venvs_dir / f"venv-{venv_hash}"
        python_executable = venv_path / "bin" / "python"

        if not python_executable.exists():
            context.fail_on_sandbox_error(
                f"Venv for hash {venv_hash} not found at {venv_path}; refusing to execute."
            )
            return

        context.python_executable = python_executable
