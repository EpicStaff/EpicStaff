import os
import shutil
import sys
import types
from pathlib import Path
from typing import Any


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
        "SANDBOX_EXECUTION_TIMEOUT": "5m",
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


def _exec_dir(base_dir: Path) -> Path:
    return base_dir / "exec"


_SHARED_LIBS_ROOT = Path(__file__).resolve().parents[3] / "shared"
# Both packages are pure Python with zero dependencies (see their
# pyproject.toml `dependencies = []`), so copying just their source files is
# enough -- no compiled artifacts, no transitive installs to reproduce.
_SHARED_LIBS_SOURCE_FILES: dict[str, tuple[str, ...]] = {
    "dotdict": ("__init__.py", "dotdict.py"),
    "epicstaff_secrets": ("__init__.py", "secrets.py"),
}


def copy_shared_libs_into_jail(base_dir: Path) -> Path:
    """Copy dotdict + epicstaff_secrets into exec_dir, inside the Landlock jail.

    wrap_code's preamble always does `from dotdict import ...` and
    `from epicstaff_secrets import get_secret`, so every execution needs both
    importable, whether or not the job code itself uses them. In production,
    CreateVenvHandler pip-installs both into the venv (see
    `predefined_libraries` in dynamic_venv_executor_chain.py), and venv_path
    sits in jail.py's read_exec, so the real chain is self-contained inside
    the jail.

    Tests that drive ExecuteCodeHandler directly skip venv creation, so
    PYTHONPATH must point somewhere the Landlock ruleset built by
    jail.build_jail actually allows reading. Pointing it at src/shared
    directly does NOT work: that path is outside every allowlist entry
    (read_write and read_exec alike), so the child gets
    ModuleNotFoundError. exec_dir (base_dir/"exec") IS inside
    jail.read_write, so copying the two packages' source there and pointing
    PYTHONPATH at the copy works without widening the jail's allowlist.
    """
    shared_libs_dir = _exec_dir(base_dir) / "shared_libs"
    for package_name, filenames in _SHARED_LIBS_SOURCE_FILES.items():
        package_dir = shared_libs_dir / package_name
        package_dir.mkdir(parents=True, exist_ok=True)
        for filename in filenames:
            shutil.copy2(
                _SHARED_LIBS_ROOT / package_name / filename,
                package_dir / filename,
            )
    return shared_libs_dir


def make_execute_context(base_dir: Path, **overrides: Any) -> dict[str, Any]:
    """Build the context dict ExecuteCodeHandler.handle() expects.

    The authoritative key set and defaults are DynamicVenvExecutorChain.run()'s
    context in dynamic_venv_executor_chain.py (~line 648): base_venv_path,
    libraries, temp_code_path, code, result_file_path, entrypoint, func_kwargs,
    execution_id, global_kwargs, home_path, tmp_path, work_dir, use_storage,
    storage_allowed_paths, storage_org_prefix, secrets. This helper builds the
    subset ExecuteCodeHandler itself reads, plus python_executable (only present
    in the real chain once CreateVenvHandler has run first).

    home_path, tmp_path (the child's HOME/TMPDIR) and work_dir (the child's cwd)
    are created on disk because tests that drive a real subprocess need them to
    exist; tests that fake the subprocess call are unaffected by the extra
    directories.

    Every caller building this context by hand independently is exactly how
    test_execute_code_handler_env.py and test_execute_code_handler_storage.py
    drifted from production and started raising KeyError for tmp_path/work_dir
    -- use this instead of hand-rolling the dict again.
    """
    exec_dir = _exec_dir(base_dir)
    home_path = exec_dir / "home"
    tmp_path = exec_dir / "tmp"
    for directory in (exec_dir, home_path, tmp_path):
        directory.mkdir(parents=True, exist_ok=True)

    context: dict[str, Any] = {
        "python_executable": base_dir / "venv" / "bin" / "python",
        "temp_code_path": exec_dir / "code.py",
        "result_file_path": exec_dir / "output.txt",
        "home_path": str(home_path),
        "tmp_path": str(tmp_path),
        "work_dir": str(exec_dir),
        "code": "def main():\n    return 1",
        "entrypoint": "main",
        "func_kwargs": {},
        "global_kwargs": {},
        "execution_id": "test-exec-id",
        "use_storage": False,
        "storage_allowed_paths": None,
        "storage_org_prefix": None,
        "secrets": None,
    }
    context.update(overrides)
    return context
