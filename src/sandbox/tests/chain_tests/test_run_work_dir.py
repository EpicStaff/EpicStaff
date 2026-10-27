"""Each execution's child runs in its own work dir, never in a directory shared across runs.

run() is driven through the real ExecuteCodeHandler; only the process spawn, `os.chown`
and `os.geteuid` are faked. A non-root test process cannot chown to another uid, and the
privilege drop branch only runs as root.
"""

import os
import sys
from pathlib import Path

import pytest

pytest.importorskip(
    "pwd",
    reason="POSIX-only: sandbox isolation requires pwd/landlock; runs in the Linux image",
)

import dynamic_venv_executor_chain
from dynamic_venv_executor_chain import (
    AbstractHandler,
    DynamicVenvExecutorChain,
    ExecuteCodeHandler,
)

EXECUTION_ID = "exec-work-dir"


class _KnownInterpreter(AbstractHandler):
    """Stands in for venv creation: hands ExecuteCodeHandler an interpreter path."""

    async def handle(self, context):
        context["python_executable"] = Path(sys.executable)
        return await super().handle(context)


@pytest.fixture
def spawned(monkeypatch, tmp_path) -> dict:
    """Record the kwargs the child process is spawned with, and fake its success."""
    recorded: dict = {}

    class _FakeProcess:
        returncode = 0

        async def communicate(self):
            return (b"", b"")

    async def _fake_create(*args, **kwargs):
        recorded.update(kwargs)
        (tmp_path / "out" / EXECUTION_ID / "output.txt").write_text('"ok"')
        return _FakeProcess()

    monkeypatch.setattr(
        dynamic_venv_executor_chain.asyncio, "create_subprocess_exec", _fake_create
    )
    return recorded


async def _run(tmp_path: Path):
    chain = DynamicVenvExecutorChain(
        output_path=tmp_path / "out",
        base_venv_path=tmp_path / "venvs",
    )
    chain.chain = _KnownInterpreter()
    chain.chain.set_next(ExecuteCodeHandler())
    return await chain.run(
        libraries=[],
        venv_name="v",
        execution_id=EXECUTION_ID,
        code="def main():\n    return 1",
    )


@pytest.mark.asyncio
async def test_child_runs_in_the_runs_own_work_dir(tmp_path, monkeypatch, spawned):
    # A leftover host setting must not pull the child back into a shared directory.
    shared_dir = tmp_path / "shared"
    shared_dir.mkdir()
    monkeypatch.setenv("CONTAINER_SAVEFILES_PATH", str(shared_dir))
    monkeypatch.chdir(shared_dir)

    result = await _run(tmp_path)

    work_dir = tmp_path / "out" / EXECUTION_ID / "work"
    assert result.returncode == 0, result.stderr
    assert Path(spawned["cwd"]) == work_dir
    assert work_dir.is_dir()
    assert "CONTAINER_SAVEFILES_PATH" not in spawned["env"]


@pytest.mark.asyncio
async def test_root_chowns_only_the_runs_own_dirs(tmp_path, monkeypatch, spawned):
    chown_calls: list[tuple[Path, int, int]] = []
    monkeypatch.setattr(
        os, "chown", lambda path, uid, gid, **kwargs: chown_calls.append((Path(path), uid, gid))
    )
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    monkeypatch.setattr(dynamic_venv_executor_chain, "SANDBOX_UID", 4242)
    monkeypatch.setattr(dynamic_venv_executor_chain, "SANDBOX_GID", 4343)
    monkeypatch.setenv("CONTAINER_SAVEFILES_PATH", str(tmp_path))
    monkeypatch.chdir(tmp_path)

    result = await _run(tmp_path)

    execution_dir = tmp_path / "out" / EXECUTION_ID
    assert result.returncode == 0, result.stderr
    assert chown_calls == [
        (execution_dir, 4242, 4343),
        (execution_dir / "home", 4242, 4343),
        (execution_dir / "tmp", 4242, 4343),
        (execution_dir / "work", 4242, 4343),
    ]
