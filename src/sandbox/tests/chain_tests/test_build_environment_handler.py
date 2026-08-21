import asyncio
import json
import os
from pathlib import Path
from typing import Any

import pytest

from dynamic_venv_executor_chain import AbstractHandler, BuildEnvironmentHandler, ExecuteCodeHandler


def _make_context(tmp_path: Path) -> dict[str, Any]:
    python_executable = tmp_path / "venv" / "bin" / "python"
    temp_code_path = tmp_path / "exec" / "code.py"
    return {
        "python_executable": python_executable,
        "temp_code_path": temp_code_path,
    }


@pytest.mark.asyncio
async def test_base_env_exact_key_set(tmp_path):
    handler = BuildEnvironmentHandler()
    context = _make_context(tmp_path)

    await handler.handle(context)

    assert set(context["env"].keys()) == {
        "LANG",
        "PYTHONUTF8",
        "PYTHONUNBUFFERED",
        "PYTHONDONTWRITEBYTECODE",
        "PATH",
        "HOME",
    }


@pytest.mark.asyncio
async def test_base_env_literal_values(tmp_path):
    handler = BuildEnvironmentHandler()
    context = _make_context(tmp_path)

    await handler.handle(context)

    env = context["env"]
    assert env["LANG"] == "C.UTF-8"
    assert env["PYTHONUTF8"] == "1"
    assert env["PYTHONUNBUFFERED"] == "1"
    assert env["PYTHONDONTWRITEBYTECODE"] == "1"


@pytest.mark.asyncio
async def test_no_host_env_leak(tmp_path, monkeypatch):
    monkeypatch.setenv("LEAK_SENTINEL", "should-not-appear")
    monkeypatch.setenv("STORAGE_ACCESS_KEY", "leaked-key")

    handler = BuildEnvironmentHandler()
    context = _make_context(tmp_path)
    # use_storage is absent — storage vars must not be copied

    await handler.handle(context)

    env = context["env"]
    assert "LEAK_SENTINEL" not in env
    assert "STORAGE_ACCESS_KEY" not in env


@pytest.mark.asyncio
async def test_path_value(tmp_path):
    handler = BuildEnvironmentHandler()
    context = _make_context(tmp_path)
    python_executable = context["python_executable"]

    await handler.handle(context)

    expected_path = os.pathsep.join(
        [str(python_executable.parent), "/usr/local/bin", "/usr/bin", "/bin"]
    )
    assert context["env"]["PATH"] == expected_path


@pytest.mark.asyncio
async def test_home_created_on_disk(tmp_path):
    handler = BuildEnvironmentHandler()
    context = _make_context(tmp_path)
    temp_code_path = context["temp_code_path"]

    await handler.handle(context)

    expected_home = str(temp_code_path.parent / "home")
    assert context["env"]["HOME"] == expected_home
    assert Path(expected_home).is_dir()


@pytest.mark.asyncio
async def test_use_storage_injects_scoped_creds_not_root(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_ENDPOINT", "http://minio:9000")
    monkeypatch.setenv("STORAGE_BUCKET_NAME", "epicstaff")
    monkeypatch.setenv("STORAGE_ACCESS_KEY", "ROOT-must-not-leak")
    monkeypatch.setenv("STORAGE_SECRET_KEY", "ROOT-must-not-leak")

    handler = BuildEnvironmentHandler()
    context = _make_context(tmp_path)
    context["use_storage"] = True
    context["temp_storage_access_key"] = "scoped-ak"
    context["temp_storage_secret_key"] = "scoped-sk"

    await handler.handle(context)

    env = context["env"]
    assert env["STORAGE_ENDPOINT"] == "http://minio:9000"
    assert env["STORAGE_BUCKET_NAME"] == "epicstaff"
    assert env["STORAGE_ACCESS_KEY"] == "scoped-ak"
    assert env["STORAGE_SECRET_KEY"] == "scoped-sk"


@pytest.mark.asyncio
async def test_use_storage_falsy_does_not_copy_storage_vars(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_ENDPOINT", "http://minio:9000")
    monkeypatch.setenv("STORAGE_ACCESS_KEY", "access")
    monkeypatch.setenv("STORAGE_SECRET_KEY", "secret")
    monkeypatch.setenv("STORAGE_BUCKET_NAME", "mybucket")

    handler = BuildEnvironmentHandler()
    context = _make_context(tmp_path)
    context["use_storage"] = False

    await handler.handle(context)

    env = context["env"]
    assert "STORAGE_ENDPOINT" not in env
    assert "STORAGE_ACCESS_KEY" not in env
    assert "STORAGE_SECRET_KEY" not in env
    assert "STORAGE_BUCKET_NAME" not in env


@pytest.mark.asyncio
async def test_storage_allowed_paths_present(tmp_path):
    handler = BuildEnvironmentHandler()
    context = _make_context(tmp_path)
    allowed = ["/data/org1", "/data/org2"]
    context["storage_allowed_paths"] = allowed

    await handler.handle(context)

    assert context["env"]["STORAGE_ALLOWED_PATHS"] == json.dumps(allowed)


@pytest.mark.asyncio
async def test_storage_allowed_paths_absent_when_none(tmp_path):
    handler = BuildEnvironmentHandler()
    context = _make_context(tmp_path)
    context["storage_allowed_paths"] = None

    await handler.handle(context)

    assert "STORAGE_ALLOWED_PATHS" not in context["env"]


@pytest.mark.asyncio
async def test_storage_allowed_paths_absent_when_key_missing(tmp_path):
    handler = BuildEnvironmentHandler()
    context = _make_context(tmp_path)
    # key not set at all

    await handler.handle(context)

    assert "STORAGE_ALLOWED_PATHS" not in context["env"]


@pytest.mark.asyncio
async def test_storage_allowed_paths_empty_list_is_present(tmp_path):
    handler = BuildEnvironmentHandler()
    context = _make_context(tmp_path)
    context["storage_allowed_paths"] = []

    await handler.handle(context)

    assert context["env"]["STORAGE_ALLOWED_PATHS"] == "[]"


@pytest.mark.asyncio
async def test_storage_org_prefix_present(tmp_path):
    handler = BuildEnvironmentHandler()
    context = _make_context(tmp_path)
    context["storage_org_prefix"] = "org/team1"

    await handler.handle(context)

    assert context["env"]["STORAGE_ORG_PREFIX"] == "org/team1"


@pytest.mark.asyncio
async def test_storage_org_prefix_absent_when_none(tmp_path):
    handler = BuildEnvironmentHandler()
    context = _make_context(tmp_path)
    context["storage_org_prefix"] = None

    await handler.handle(context)

    assert "STORAGE_ORG_PREFIX" not in context["env"]


@pytest.mark.asyncio
async def test_storage_org_prefix_absent_when_key_missing(tmp_path):
    handler = BuildEnvironmentHandler()
    context = _make_context(tmp_path)

    await handler.handle(context)

    assert "STORAGE_ORG_PREFIX" not in context["env"]


@pytest.mark.asyncio
async def test_secrets_present(tmp_path):
    handler = BuildEnvironmentHandler()
    context = _make_context(tmp_path)
    secrets = {"API_KEY": "abc123", "TOKEN": "xyz"}
    context["secrets"] = secrets

    await handler.handle(context)

    assert context["env"]["EPICSTAFF_SECRETS"] == json.dumps(secrets)


@pytest.mark.asyncio
async def test_secrets_absent_when_none(tmp_path):
    handler = BuildEnvironmentHandler()
    context = _make_context(tmp_path)
    context["secrets"] = None

    await handler.handle(context)

    assert "EPICSTAFF_SECRETS" not in context["env"]


@pytest.mark.asyncio
async def test_secrets_absent_when_key_missing(tmp_path):
    handler = BuildEnvironmentHandler()
    context = _make_context(tmp_path)

    await handler.handle(context)

    assert "EPICSTAFF_SECRETS" not in context["env"]


@pytest.mark.asyncio
async def test_context_env_is_set(tmp_path):
    handler = BuildEnvironmentHandler()
    context = _make_context(tmp_path)

    await handler.handle(context)

    assert "env" in context
    assert isinstance(context["env"], dict)


@pytest.mark.asyncio
async def test_terminal_handler_returns_environment_built(tmp_path):
    handler = BuildEnvironmentHandler()
    context = _make_context(tmp_path)

    result = await handler.handle(context)

    assert result == "Environment built."


@pytest.mark.asyncio
async def test_delegation_to_next_handler(tmp_path):
    class RecordingHandler(AbstractHandler):
        received_context: dict | None = None

        async def handle(self, context: dict) -> Any:
            RecordingHandler.received_context = context
            return "sentinel-from-next"

    handler = BuildEnvironmentHandler()
    next_handler = RecordingHandler()
    handler.set_next(next_handler)
    context = _make_context(tmp_path)

    result = await handler.handle(context)

    assert result == "sentinel-from-next"
    assert RecordingHandler.received_context is context


@pytest.mark.asyncio
async def test_execute_code_handler_uses_curated_env(tmp_path, monkeypatch):
    recorded_kwargs: dict = {}

    class FakeProcess:
        returncode = 0

        async def communicate(self):
            return (b"", b"")

    async def fake_create_subprocess_shell(cmd, **kwargs):
        recorded_kwargs.update(kwargs)
        return FakeProcess()

    import dynamic_venv_executor_chain
    monkeypatch.setattr(
        dynamic_venv_executor_chain.asyncio,
        "create_subprocess_shell",
        fake_create_subprocess_shell,
    )

    curated_env = {"CURATED": "yes"}

    exec_dir = tmp_path / "exec"
    exec_dir.mkdir(parents=True, exist_ok=True)
    temp_code_path = exec_dir / "code.py"
    result_file_path = exec_dir / "output.txt"
    result_file_path.write_text('"ok"')

    context = {
        "python_executable": "/fake/venv/bin/python",
        "temp_code_path": temp_code_path,
        "result_file_path": result_file_path,
        "code": "def main():\n    return 1",
        "entrypoint": "main",
        "func_kwargs": {},
        "global_kwargs": {},
        "execution_id": "x",
        "use_storage": False,
        "env": curated_env,
    }

    handler = ExecuteCodeHandler()
    await handler.handle(context)

    assert recorded_kwargs["env"] is curated_env
