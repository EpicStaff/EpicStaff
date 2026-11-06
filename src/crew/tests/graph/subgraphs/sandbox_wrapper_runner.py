"""Run code through the sandbox's own wrapper, in a subprocess, the way the sandbox runs it.

The decision tables' error messages depend on what the sandbox reports for the code crew
generates: the one line it writes to stderr and the line number in it. Running the real
``wrap_code`` keeps these tests from passing against a copy that drifted from it. Only
the wrapper runs: the isolation the sandbox adds around it doesn't change the messages.
"""

import os
import secrets
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from src.sandbox_new.worker.infrastructure.execution.code_wrapper import wrap_code

# The wrapper imports epicstaff_secrets, a top-level package of src/shared in the sandbox.
_SHARED_DIR = Path(__file__).resolve().parents[4] / "shared"


def run_in_sandbox_wrapper(
    code: str,
    entrypoint: str,
    inputs: dict[str, Any],
    extra_python_path: tuple[str, ...] = (),
    extra_environment: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Return the result the sandbox would send crew for running ``code``.

    ``extra_python_path`` comes first on the path, so a test can stand in for a library
    the code imports; ``extra_environment`` is added to the code's environment.
    """
    with tempfile.TemporaryDirectory() as directory:
        result_path = Path(directory) / "result.json"
        source = wrap_code(
            code=code,
            result_file_path=result_path,
            entrypoint=entrypoint,
            func_kwargs=inputs,
            result_write_marker=secrets.token_hex(16),
        )
        python_path = os.pathsep.join(
            path
            for path in (*extra_python_path, str(_SHARED_DIR), os.environ.get("PYTHONPATH"))
            if path
        )
        environment = {**os.environ, **(extra_environment or {}), "PYTHONPATH": python_path}
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

    def __init__(
        self,
        extra_python_path: tuple[str, ...] = (),
        extra_environment: dict[str, str] | None = None,
    ) -> None:
        self.calls: list[dict[str, Any]] = []
        self.extra_python_path = extra_python_path
        self.extra_environment = extra_environment

    async def run_code(
        self,
        python_code_data,
        inputs,
        additional_global_kwargs=None,
        stop_event=None,
        storage_credentials=None,
    ) -> dict[str, Any]:
        self.calls.append(inputs)
        return run_in_sandbox_wrapper(
            python_code_data.code,
            python_code_data.entrypoint,
            inputs,
            extra_python_path=self.extra_python_path,
            extra_environment=self.extra_environment,
        )
