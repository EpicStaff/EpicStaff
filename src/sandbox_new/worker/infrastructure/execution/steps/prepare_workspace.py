"""Creates the per-execution workspace and the environment for the child.

Each execution gets its own ``exec_dir`` (with ``home``, ``tmp`` and ``work`` under
it) so runs never share writable state; the orchestrator deletes it after the run.
``work`` is the child's cwd: a subdir, so a relative write such as ``output.txt``
cannot replace the control files (code.py, output.txt, storage_mutations.json) kept
in ``exec_dir``. When the worker runs as root these dirs are chowned to
``sandboxuser`` so the dropped child can write into them. Storage environment
variables are added later, by the storage step.
"""

import json
import os
from pathlib import Path

from loguru import logger

from worker.application.context import ExecutionContext
from worker.infrastructure.execution.environment import build_base_env
from worker.infrastructure.execution.privileges import (
    SANDBOX_GID,
    SANDBOX_UID,
    can_drop_privileges,
)

__all__ = ["PrepareWorkspaceStep"]


class PrepareWorkspaceStep:
    def __init__(self, *, executions_dir: Path):
        self._executions_dir = executions_dir

    async def __call__(self, context: ExecutionContext) -> None:
        job = context.job
        exec_dir = self._executions_dir / job.execution_id
        home_dir = exec_dir / "home"
        tmp_dir = exec_dir / "tmp"
        work_dir = exec_dir / "work"

        # Set before anything here can fail: the orchestrator removes the workspace
        # only when it knows the path.
        context.exec_dir = exec_dir
        for directory in (exec_dir, home_dir, tmp_dir, work_dir):
            directory.mkdir(parents=True, exist_ok=True)

        if can_drop_privileges():
            try:
                for directory in (exec_dir, home_dir, tmp_dir, work_dir):
                    os.chown(directory, SANDBOX_UID, SANDBOX_GID)
            except OSError as error:
                logger.error("Failed to chown execution dirs (EPERM?): {}", error)
                context.fail(f"Security setup failed: could not chown execution dirs: {error}")
                return

        context.home_dir = home_dir
        context.tmp_dir = tmp_dir
        context.work_dir = work_dir
        context.code_path = exec_dir / "code.py"
        context.result_file_path = exec_dir / "output.txt"

        env = build_base_env(context.python_executable)
        env["HOME"] = str(home_dir)
        env["TMPDIR"] = str(tmp_dir)
        env["EPICSTAFF_SECRETS"] = json.dumps(job.secrets)
        context.env = env
