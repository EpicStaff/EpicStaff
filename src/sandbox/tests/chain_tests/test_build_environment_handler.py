import json
import os
from pathlib import Path
from typing import Any

import pytest

from dynamic_venv_executor_chain import AbstractHandler, ExecuteCodeHandler
from utils.environment import build_base_env

_SENSITIVE_KEYS = {
    "STORAGE_ENDPOINT",
    "STORAGE_BUCKET_NAME",
    "STORAGE_ACCESS_KEY",
    "STORAGE_SECRET_KEY",
    "STORAGE_ALLOWED_PATHS",
    "STORAGE_ORG_PREFIX",
}


def _make_execute_context(tmp_path: Path, **overrides) -> dict[str, Any]:
    """Build a minimal valid context for ExecuteCodeHandler.

    The handler writes to temp_code_path (parent must exist) and reads
    result_file_path after the subprocess returns.  The caller is responsible
    for pre-writing result_file_path with valid JSON before driving the handler.
    """
    exec_dir = tmp_path / "exec"
    exec_dir.mkdir(parents=True, exist_ok=True)

    ctx: dict[str, Any] = {
        "python_executable": tmp_path / "venv" / "bin" / "python",
        "temp_code_path": exec_dir / "code.py",
        "result_file_path": exec_dir / "output.txt",
        "home_path": str(exec_dir / "home"),
        "code": "def main():\n    return 1",
        "entrypoint": "main",
        "func_kwargs": {},
        "global_kwargs": {},
        "execution_id": "test-exec-id",
        "use_storage": False,
    }
    ctx.update(overrides)
    return ctx


# ---------------------------------------------------------------------------
# Shared fake-subprocess fixture used by all ExecuteCodeHandler tests
# ---------------------------------------------------------------------------


def _patch_subprocess(monkeypatch, recorded: dict, result_file_path: Path) -> None:
    """Monkeypatch asyncio.create_subprocess_exec to record env and fake success.

    The fake pre-writes result_file_path so the handler can read it after the
    subprocess call without requiring a real interpreter.
    """

    class _FakeProcess:
        returncode = 0

        async def communicate(self):
            return (b"", b"")

    async def _fake_create(*args, **kwargs):
        recorded.update(kwargs)
        # Pre-write the result file so the handler can read it
        result_file_path.write_text('"ok"')
        return _FakeProcess()

    import dynamic_venv_executor_chain

    monkeypatch.setattr(
        dynamic_venv_executor_chain.asyncio,
        "create_subprocess_exec",
        _fake_create,
    )


# ---------------------------------------------------------------------------
# build_base_env — key set and literal values
# ---------------------------------------------------------------------------


def test_build_base_env_exact_key_set(tmp_path):
    python_executable = tmp_path / "venv" / "bin" / "python"
    env = build_base_env(python_executable)
    assert set(env.keys()) == {
        "LANG",
        "PYTHONUTF8",
        "PYTHONUNBUFFERED",
        "PYTHONDONTWRITEBYTECODE",
        "PATH",
    }
    assert "HOME" not in env


def test_build_base_env_literal_values(tmp_path):
    python_executable = tmp_path / "venv" / "bin" / "python"
    env = build_base_env(python_executable)
    assert env["LANG"] == "C.UTF-8"
    assert env["PYTHONUTF8"] == "1"
    assert env["PYTHONUNBUFFERED"] == "1"
    assert env["PYTHONDONTWRITEBYTECODE"] == "1"


def test_build_base_env_path_contains_venv_bin(tmp_path):
    python_executable = tmp_path / "venv" / "bin" / "python"
    env = build_base_env(python_executable)
    path_parts = env["PATH"].split(os.pathsep)
    assert str(python_executable.parent) == path_parts[0]
    assert "/usr/local/bin" in path_parts
    assert "/usr/bin" in path_parts
    assert "/bin" in path_parts


def test_build_base_env_path_ordering(tmp_path):
    python_executable = tmp_path / "venv" / "bin" / "python"
    env = build_base_env(python_executable)
    expected = os.pathsep.join(
        [str(python_executable.parent), "/usr/local/bin", "/usr/bin", "/bin"]
    )
    assert env["PATH"] == expected


# ---------------------------------------------------------------------------
# SECURITY REGRESSION — build_base_env must not contain any sensitive key
# ---------------------------------------------------------------------------


def test_build_base_env_contains_no_sensitive_keys(tmp_path, monkeypatch):
    """Regression: pip runs with base env only — no secrets must leak."""
    monkeypatch.setenv("STORAGE_ACCESS_KEY", "root-ak-must-not-leak")
    monkeypatch.setenv("STORAGE_SECRET_KEY", "root-sk-must-not-leak")
    monkeypatch.setenv("STORAGE_ENDPOINT", "http://minio:9000")
    monkeypatch.setenv("STORAGE_BUCKET_NAME", "mybucket")
    monkeypatch.setenv("REDIS_PASSWORD", "redis-secret")
    monkeypatch.setenv("ARBITRARY_SECRET", "arbitrary")

    python_executable = tmp_path / "venv" / "bin" / "python"
    env = build_base_env(python_executable)

    for key in _SENSITIVE_KEYS:
        assert key not in env, f"Sensitive key leaked into base env: {key}"

    assert "REDIS_PASSWORD" not in env
    assert "ARBITRARY_SECRET" not in env


# ---------------------------------------------------------------------------
# ExecuteCodeHandler — base keys and HOME always present
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_code_handler_base_keys_present(tmp_path, monkeypatch):
    """Handler env must contain all base keys from build_base_env."""
    recorded: dict = {}
    context = _make_execute_context(tmp_path)
    _patch_subprocess(monkeypatch, recorded, context["result_file_path"])

    await ExecuteCodeHandler().handle(context)

    env = recorded["env"]
    assert "LANG" in env
    assert "PYTHONUTF8" in env
    assert "PYTHONUNBUFFERED" in env
    assert "PYTHONDONTWRITEBYTECODE" in env
    assert "PATH" in env


@pytest.mark.asyncio
async def test_execute_code_handler_home_equals_home_path(tmp_path, monkeypatch):
    """Handler sets env['HOME'] from context['home_path'], not 'home_dir'."""
    recorded: dict = {}
    context = _make_execute_context(tmp_path)
    _patch_subprocess(monkeypatch, recorded, context["result_file_path"])

    await ExecuteCodeHandler().handle(context)

    assert recorded["env"]["HOME"] == context["home_path"]


# ---------------------------------------------------------------------------
# ExecuteCodeHandler — use_storage=True injects scoped creds, not root creds
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_code_handler_use_storage_injects_scoped_creds_not_root(
    tmp_path, monkeypatch
):
    """Regression: scoped keys from context must win over root env keys."""
    monkeypatch.setenv("STORAGE_ENDPOINT", "http://minio:9000")
    monkeypatch.setenv("STORAGE_BUCKET_NAME", "epicstaff")
    # Root credentials — must NOT appear in the subprocess env
    monkeypatch.setenv("STORAGE_ACCESS_KEY", "ROOT-must-not-leak")
    monkeypatch.setenv("STORAGE_SECRET_KEY", "ROOT-must-not-leak")

    recorded: dict = {}
    context = _make_execute_context(
        tmp_path,
        use_storage=True,
        temp_storage_access_key="scoped-ak",
        temp_storage_secret_key="scoped-sk",
    )
    _patch_subprocess(monkeypatch, recorded, context["result_file_path"])

    await ExecuteCodeHandler().handle(context)

    env = recorded["env"]
    assert env["STORAGE_ENDPOINT"] == "http://minio:9000"
    assert env["STORAGE_BUCKET_NAME"] == "epicstaff"
    assert env["STORAGE_ACCESS_KEY"] == "scoped-ak"
    assert env["STORAGE_SECRET_KEY"] == "scoped-sk"


@pytest.mark.asyncio
async def test_execute_code_handler_use_storage_false_omits_storage_vars(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("STORAGE_ENDPOINT", "http://minio:9000")
    monkeypatch.setenv("STORAGE_ACCESS_KEY", "access")
    monkeypatch.setenv("STORAGE_SECRET_KEY", "secret")
    monkeypatch.setenv("STORAGE_BUCKET_NAME", "mybucket")

    recorded: dict = {}
    context = _make_execute_context(tmp_path, use_storage=False)
    _patch_subprocess(monkeypatch, recorded, context["result_file_path"])

    await ExecuteCodeHandler().handle(context)

    env = recorded["env"]
    assert "STORAGE_ENDPOINT" not in env
    assert "STORAGE_ACCESS_KEY" not in env
    assert "STORAGE_SECRET_KEY" not in env
    assert "STORAGE_BUCKET_NAME" not in env


@pytest.mark.asyncio
async def test_execute_code_handler_use_storage_absent_omits_storage_vars(
    tmp_path, monkeypatch
):
    recorded: dict = {}
    # use_storage not in context at all
    context = _make_execute_context(tmp_path)
    del context["use_storage"]
    _patch_subprocess(monkeypatch, recorded, context["result_file_path"])

    await ExecuteCodeHandler().handle(context)

    env = recorded["env"]
    assert "STORAGE_ENDPOINT" not in env
    assert "STORAGE_ACCESS_KEY" not in env
    assert "STORAGE_SECRET_KEY" not in env
    assert "STORAGE_BUCKET_NAME" not in env


# ---------------------------------------------------------------------------
# ExecuteCodeHandler — storage_allowed_paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_code_handler_storage_allowed_paths_present(tmp_path, monkeypatch):
    allowed = ["/data/org1", "/data/org2"]
    recorded: dict = {}
    context = _make_execute_context(tmp_path, storage_allowed_paths=allowed)
    _patch_subprocess(monkeypatch, recorded, context["result_file_path"])

    await ExecuteCodeHandler().handle(context)

    assert recorded["env"]["STORAGE_ALLOWED_PATHS"] == json.dumps(allowed)


@pytest.mark.asyncio
async def test_execute_code_handler_storage_allowed_paths_empty_list_serialised(
    tmp_path, monkeypatch
):
    recorded: dict = {}
    context = _make_execute_context(tmp_path, storage_allowed_paths=[])
    _patch_subprocess(monkeypatch, recorded, context["result_file_path"])

    await ExecuteCodeHandler().handle(context)

    assert recorded["env"]["STORAGE_ALLOWED_PATHS"] == "[]"


@pytest.mark.asyncio
async def test_execute_code_handler_storage_allowed_paths_none_omits_key(
    tmp_path, monkeypatch
):
    recorded: dict = {}
    context = _make_execute_context(tmp_path, storage_allowed_paths=None)
    _patch_subprocess(monkeypatch, recorded, context["result_file_path"])

    await ExecuteCodeHandler().handle(context)

    assert "STORAGE_ALLOWED_PATHS" not in recorded["env"]


@pytest.mark.asyncio
async def test_execute_code_handler_storage_allowed_paths_missing_omits_key(
    tmp_path, monkeypatch
):
    recorded: dict = {}
    context = _make_execute_context(tmp_path)
    # storage_allowed_paths not set at all
    _patch_subprocess(monkeypatch, recorded, context["result_file_path"])

    await ExecuteCodeHandler().handle(context)

    assert "STORAGE_ALLOWED_PATHS" not in recorded["env"]


# ---------------------------------------------------------------------------
# ExecuteCodeHandler — storage_org_prefix
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_code_handler_storage_org_prefix_present(tmp_path, monkeypatch):
    recorded: dict = {}
    context = _make_execute_context(tmp_path, storage_org_prefix="org/team1")
    _patch_subprocess(monkeypatch, recorded, context["result_file_path"])

    await ExecuteCodeHandler().handle(context)

    assert recorded["env"]["STORAGE_ORG_PREFIX"] == "org/team1"


@pytest.mark.asyncio
async def test_execute_code_handler_storage_org_prefix_none_omits_key(
    tmp_path, monkeypatch
):
    recorded: dict = {}
    context = _make_execute_context(tmp_path, storage_org_prefix=None)
    _patch_subprocess(monkeypatch, recorded, context["result_file_path"])

    await ExecuteCodeHandler().handle(context)

    assert "STORAGE_ORG_PREFIX" not in recorded["env"]


@pytest.mark.asyncio
async def test_execute_code_handler_storage_org_prefix_missing_omits_key(
    tmp_path, monkeypatch
):
    recorded: dict = {}
    context = _make_execute_context(tmp_path)
    _patch_subprocess(monkeypatch, recorded, context["result_file_path"])

    await ExecuteCodeHandler().handle(context)

    assert "STORAGE_ORG_PREFIX" not in recorded["env"]


# ---------------------------------------------------------------------------
# SECURITY REGRESSION — EPICSTAFF_SECRETS concept is gone
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_code_handler_epicstaff_secrets_never_injected(
    tmp_path, monkeypatch
):
    """Regression: even if a 'secrets' key exists in context, EPICSTAFF_SECRETS
    must never appear in the subprocess env — the feature was removed."""
    recorded: dict = {}
    context = _make_execute_context(tmp_path)
    context["secrets"] = {"API_KEY": "abc123", "TOKEN": "xyz"}
    _patch_subprocess(monkeypatch, recorded, context["result_file_path"])

    await ExecuteCodeHandler().handle(context)

    assert "EPICSTAFF_SECRETS" not in recorded["env"]


# ---------------------------------------------------------------------------
# ExecuteCodeHandler — existing smoke-test (kept for non-regression)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_code_handler_uses_execution_env(tmp_path, monkeypatch):
    """ExecuteCodeHandler must build env inline — not read context['env']."""
    recorded: dict = {}

    class FakeProcess:
        returncode = 0

        async def communicate(self):
            return (b"", b"")

    async def fake_create_subprocess_exec(*args, **kwargs):
        recorded.update(kwargs)
        return FakeProcess()

    import dynamic_venv_executor_chain

    monkeypatch.setattr(
        dynamic_venv_executor_chain.asyncio,
        "create_subprocess_exec",
        fake_create_subprocess_exec,
    )

    exec_dir = tmp_path / "exec"
    exec_dir.mkdir(parents=True, exist_ok=True)
    temp_code_path = exec_dir / "code.py"
    result_file_path = exec_dir / "output.txt"
    result_file_path.write_text('"ok"')

    context = {
        "python_executable": tmp_path / "venv" / "bin" / "python",
        "temp_code_path": temp_code_path,
        "result_file_path": result_file_path,
        "home_path": str(exec_dir / "home"),
        "code": "def main():\n    return 1",
        "entrypoint": "main",
        "func_kwargs": {},
        "global_kwargs": {},
        "execution_id": "x",
        "use_storage": False,
    }

    handler = ExecuteCodeHandler()
    await handler.handle(context)

    # env must be present and must be a dict (built inline in the handler)
    assert "env" in recorded
    assert isinstance(recorded["env"], dict)
    # base keys always present
    assert "LANG" in recorded["env"]
    assert "PATH" in recorded["env"]
    # no stale context["env"] key should have been used (context has no "env")
    assert "env" not in context
