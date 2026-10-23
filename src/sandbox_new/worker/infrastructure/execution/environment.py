"""The minimal base environment handed to the execution subprocess.

Pure -- no I/O. Deliberately does not inherit ``os.environ``: the child gets only
these curated variables plus whatever the workspace and storage steps add, so the
worker's own environment (and any credentials in it) never leaks into user code.
"""

import os
from pathlib import Path

__all__ = ["build_base_env"]


def build_base_env(python_executable: str | Path) -> dict[str, str]:
    venv_bin = Path(python_executable).parent
    return {
        "LANG": "C.UTF-8",
        "PYTHONUTF8": "1",
        "PYTHONUNBUFFERED": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PATH": os.pathsep.join([str(venv_bin), "/usr/local/bin", "/usr/bin", "/bin"]),
    }
