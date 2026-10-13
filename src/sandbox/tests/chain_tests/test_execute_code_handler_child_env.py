import json
import os
from pathlib import Path

import pytest

pytest.importorskip(
    "pwd",
    reason="POSIX-only: sandbox isolation requires pwd/landlock; runs in the Linux image",
)

import settings

from dynamic_venv_executor_chain import ExecuteCodeHandler

from conftest import make_execute_context as _make_execute_context

_SENSITIVE_KEYS = {
    "STORAGE_ENDPOINT",
    "STORAGE_BUCKET_NAME",
    "STORAGE_ACCESS_KEY",
    "STORAGE_SECRET_KEY",
    "STORAGE_ALLOWED_PATHS",
    "STORAGE_ORG_PREFIX",
    "STORAGE_USER",
    "STORAGE_PASSWORD",
}


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


async def _child_env(tmp_path, monkeypatch, *, drop_keys=(), **context_overrides) -> dict:
    """The environment ExecuteCodeHandler hands the child process."""
    recorded: dict = {}
    context = _make_execute_context(tmp_path, **context_overrides)
    for key in drop_keys:
        del context[key]
    _patch_subprocess(monkeypatch, recorded, context["result_file_path"])
    await ExecuteCodeHandler().handle(context)
    return recorded["env"]


@pytest.mark.asyncio
async def test_child_env_is_built_from_scratch_not_inherited(tmp_path, monkeypatch):
    for name, value in {
        "STORAGE_ACCESS_KEY": "root-ak-must-not-leak",
        "STORAGE_SECRET_KEY": "root-sk-must-not-leak",
        "STORAGE_USER": "root-user-must-not-leak",
        "STORAGE_PASSWORD": "root-password-must-not-leak",
        "REDIS_PASSWORD": "redis-secret",
        "ARBITRARY_SECRET": "arbitrary",
    }.items():
        monkeypatch.setenv(name, value)

    env = await _child_env(tmp_path, monkeypatch)

    assert not set(env) & (_SENSITIVE_KEYS | {"REDIS_PASSWORD", "ARBITRARY_SECRET"})
    assert env["HOME"] == str(tmp_path / "exec" / "home")
    venv_bin = str(tmp_path / "venv" / "bin")
    assert env["PATH"].split(os.pathsep) == [venv_bin, "/usr/local/bin", "/usr/bin", "/bin"]
    assert env["LANG"] == "C.UTF-8"


@pytest.mark.asyncio
async def test_storage_gets_scoped_credentials_never_the_root_ones(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "STORAGE_ENDPOINT", "http://storage:9000")
    monkeypatch.setattr(settings, "STORAGE_BUCKET_NAME", "epicstaff")
    for name in ("STORAGE_ACCESS_KEY", "STORAGE_SECRET_KEY", "STORAGE_USER", "STORAGE_PASSWORD"):
        monkeypatch.setenv(name, "ROOT-must-not-leak")

    env = await _child_env(
        tmp_path,
        monkeypatch,
        use_storage=True,
        temp_storage_access_key="scoped-ak",
        temp_storage_secret_key="scoped-sk",
    )

    assert {name: env.get(name) for name in (
        "STORAGE_ENDPOINT", "STORAGE_BUCKET_NAME", "STORAGE_ACCESS_KEY", "STORAGE_SECRET_KEY",
        "STORAGE_USER", "STORAGE_PASSWORD",
    )} == {
        "STORAGE_ENDPOINT": "http://storage:9000",
        "STORAGE_BUCKET_NAME": "epicstaff",
        "STORAGE_ACCESS_KEY": "scoped-ak",
        "STORAGE_SECRET_KEY": "scoped-sk",
        "STORAGE_USER": None,
        "STORAGE_PASSWORD": None,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("overrides", "drop_keys"),
    [({"use_storage": False}, ()), ({}, ("use_storage",))],
    ids=["use-storage-false", "use-storage-absent"],
)
async def test_no_storage_variables_without_storage(tmp_path, monkeypatch, overrides, drop_keys):
    for name in ("STORAGE_ENDPOINT", "STORAGE_ACCESS_KEY", "STORAGE_SECRET_KEY", "STORAGE_BUCKET_NAME"):
        monkeypatch.setenv(name, "host-value")

    env = await _child_env(tmp_path, monkeypatch, drop_keys=drop_keys, **overrides)

    assert not set(env) & {
        "STORAGE_ENDPOINT", "STORAGE_ACCESS_KEY", "STORAGE_SECRET_KEY", "STORAGE_BUCKET_NAME",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("context_key", "env_key", "value", "expected"),
    [
        ("storage_allowed_paths", "STORAGE_ALLOWED_PATHS", ["/data/org1", "/data/org2"],
         json.dumps(["/data/org1", "/data/org2"])),
        # An empty allowlist must reach the child as "nothing allowed", not as "unset".
        ("storage_allowed_paths", "STORAGE_ALLOWED_PATHS", [], "[]"),
        ("storage_allowed_paths", "STORAGE_ALLOWED_PATHS", None, None),
        ("storage_allowed_paths", "STORAGE_ALLOWED_PATHS", "missing", None),
        ("storage_org_prefix", "STORAGE_ORG_PREFIX", "org/team1", "org/team1"),
        ("storage_org_prefix", "STORAGE_ORG_PREFIX", None, None),
        ("storage_org_prefix", "STORAGE_ORG_PREFIX", "missing", None),
        ("secrets", "EPICSTAFF_SECRETS", {"API_KEY": "abc123", "TOKEN": "xyz"},
         json.dumps({"API_KEY": "abc123", "TOKEN": "xyz"})),
    ],
)
async def test_context_value_reaches_the_child_env(
    tmp_path, monkeypatch, context_key, env_key, value, expected
):
    if value == "missing":
        env = await _child_env(tmp_path, monkeypatch, drop_keys=(context_key,))
    else:
        env = await _child_env(tmp_path, monkeypatch, **{context_key: value})

    assert env.get(env_key) == expected
