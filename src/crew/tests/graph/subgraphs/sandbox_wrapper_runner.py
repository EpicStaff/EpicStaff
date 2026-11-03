"""Run code through the sandbox's own wrapper, in a subprocess, the way the sandbox runs it.

The decision tables' error messages depend on what the sandbox reports for the code crew
generates: the one line it writes to stderr and the line number in it. Running the real
``wrap_code`` keeps these tests from passing against a copy that drifted from it. Only
the wrapper runs: the isolation the sandbox adds around it doesn't change the messages.
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from src.sandbox_new.worker.infrastructure.execution.code_wrapper import wrap_code

# The wrapper imports epicstaff_secrets, a top-level package of src/shared in the sandbox.
_SHARED_DIR = Path(__file__).resolve().parents[4] / "shared"


def run_in_sandbox_wrapper(code: str, entrypoint: str, inputs: dict[str, Any]) -> dict[str, Any]:
    """Return the result the sandbox would send crew for running ``code``."""
    with tempfile.TemporaryDirectory() as directory:
        result_path = Path(directory) / "result.json"
        source = wrap_code(
            code=code, result_file_path=result_path, entrypoint=entrypoint, func_kwargs=inputs
        )
        python_path = os.pathsep.join(
            path for path in (str(_SHARED_DIR), os.environ.get("PYTHONPATH")) if path
        )
        environment = {**os.environ, "PYTHONPATH": python_path}
        environment.pop("SANDBOX_NETWORK_BLOCKED", None)
        completed = subprocess.run(
            [sys.executable, "-c", source],
            capture_output=True,
            text=True,
            env=environment,
            timeout=60,
            check=False,
        )
        result_data = result_path.read_text(encoding="utf-8") if completed.returncode == 0 else None
    return {
        "execution_id": "test",
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "result_data": result_data,
    }


class SandboxWrapperRunCodeService:
    """Stands in for RunPythonCodeService, running every code through the sandbox's wrapper."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def run_code(
        self,
        python_code_data,
        inputs,
        additional_global_kwargs=None,
        stop_event=None,
        storage_credentials=None,
    ) -> dict[str, Any]:
        self.calls.append(inputs)
        return run_in_sandbox_wrapper(python_code_data.code, python_code_data.entrypoint, inputs)
