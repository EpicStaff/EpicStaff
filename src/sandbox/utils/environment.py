import os
from pathlib import Path


def build_base_env(python_executable: str | Path) -> dict[str, str]:
    """Build the minimal environment for pip subprocesses. Pure function — no I/O."""
    venv_bin = Path(python_executable).parent
    return {
        "LANG": "C.UTF-8",
        "PYTHONUTF8": "1",
        "PYTHONUNBUFFERED": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PATH": os.pathsep.join([str(venv_bin), "/usr/local/bin", "/usr/bin", "/bin"]),
    }
