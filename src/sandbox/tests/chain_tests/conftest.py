import os
import sys
import types
from pathlib import Path


def _set_env_defaults() -> None:
    """Set sensible defaults for every var settings.py reads at import time.

    settings.py checks RUN_IN_DOCKER first; setting it to "true" skips the
    ../.env read, so all other vars must be provided here as well.
    """
    defaults = {
        "RUN_IN_DOCKER": "true",
        "REDIS_HOST": "localhost",
        "REDIS_PORT": "6379",
        "REDIS_USER": "test",
        "REDIS_PASSWORD": "test",
        "CODE_RESULT_CHANNEL": "code_results",
        "CODE_EXEC_CHANNEL": "code_exec_tasks",
        "STORAGE_MUTATION_CHANNEL": "storage_mutations",
        "SANDBOX_OUTPUT_PATH": "/tmp",
        "SANDBOX_BASE_VENV_PATH": "/tmp",
        "MINIO_HOST": "localhost",
        "MINIO_PORT": "9000",
        "MINIO_USER": "minioadmin",
        "MINIO_PASSWORD": "minioadmin",
        "MINIO_BUCKET": "epicstaff",
        "MINIO_SSL": "false",
        "SANDBOX_MASK_SECRET": "true",
    }
    for key, value in defaults.items():
        os.environ.setdefault(key, value)


def _ensure_src_shared_stub() -> None:
    if "src.shared.models" in sys.modules:
        return

    import dataclasses

    @dataclasses.dataclass
    class CodeResultData:
        execution_id: str
        result_data: str | None = None
        stderr: str = ""
        stdout: str = ""
        returncode: int = 0

    @dataclasses.dataclass
    class CodeTaskData:
        venv_name: str
        libraries: list
        code: str
        execution_id: str
        entrypoint: str
        func_kwargs: dict = dataclasses.field(default_factory=dict)
        global_kwargs: dict = dataclasses.field(default_factory=dict)
        secrets: dict = dataclasses.field(default_factory=dict)

    # src.shared must be a real package pointing at the actual shared/ directory
    # so that src.shared.envtools (and its `from . import humanize`) resolves.
    # conftest is at .../src/sandbox/tests/chain_tests/conftest.py; parents[3] is src/.
    shared_dir = Path(__file__).resolve().parents[3] / "shared"

    src_mod = types.ModuleType("src")
    src_shared_mod = types.ModuleType("src.shared")
    src_shared_mod.__path__ = [str(shared_dir)]
    src_shared_mod.__package__ = "src.shared"

    src_shared_models_mod = types.ModuleType("src.shared.models")
    src_shared_models_mod.CodeResultData = CodeResultData
    src_shared_models_mod.CodeTaskData = CodeTaskData

    src_mod.shared = src_shared_mod
    src_shared_mod.models = src_shared_models_mod

    sys.modules.setdefault("src", src_mod)
    sys.modules.setdefault("src.shared", src_shared_mod)
    # Register the stub so the real models module is never imported.
    sys.modules["src.shared.models"] = src_shared_models_mod


# Env defaults must be set before anything imports settings.py.
_set_env_defaults()
_ensure_src_shared_stub()
