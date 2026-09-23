"""CreateVenvHandler must install epicstaff_common into every sandbox venv,
unconditionally — unlike epicstaff_storage, which is gated behind
context["use_storage"].
"""

from pathlib import Path
from typing import Any

import pytest

pytest.importorskip(
    "pwd",
    reason="POSIX-only: sandbox isolation requires pwd/landlock; runs in the Linux image",
)

from dynamic_venv_executor_chain import CreateVenvHandler


class _FakeProcess:
    returncode = 0

    async def communicate(self):
        return (b"", b"")


def _make_context(tmp_path: Path, **overrides) -> dict[str, Any]:
    base_venv_path = tmp_path / "venvs"
    base_venv_path.mkdir(parents=True, exist_ok=True)
    context: dict[str, Any] = {
        "libraries": [],
        "base_venv_path": base_venv_path,
    }
    context.update(overrides)
    return context


@pytest.mark.asyncio
async def test_epicstaff_common_installed_when_use_storage_absent(
    tmp_path, monkeypatch
):
    import dynamic_venv_executor_chain

    async def _fake_shell(cmd, **kwargs):
        venv_path_str = cmd.strip().split()[-1]
        Path(venv_path_str).mkdir(parents=True, exist_ok=True)
        return _FakeProcess()

    monkeypatch.setattr(
        dynamic_venv_executor_chain.asyncio, "create_subprocess_shell", _fake_shell
    )

    context = _make_context(tmp_path)
    await CreateVenvHandler().handle(context)

    assert "/app/src/shared/epicstaff_common" in context["libraries"]


@pytest.mark.asyncio
async def test_epicstaff_common_installed_when_use_storage_false(
    tmp_path, monkeypatch
):
    import dynamic_venv_executor_chain

    async def _fake_shell(cmd, **kwargs):
        venv_path_str = cmd.strip().split()[-1]
        Path(venv_path_str).mkdir(parents=True, exist_ok=True)
        return _FakeProcess()

    monkeypatch.setattr(
        dynamic_venv_executor_chain.asyncio, "create_subprocess_shell", _fake_shell
    )

    context = _make_context(tmp_path, use_storage=False)
    await CreateVenvHandler().handle(context)

    assert "/app/src/shared/epicstaff_common" in context["libraries"]


@pytest.mark.asyncio
async def test_epicstaff_common_installed_when_use_storage_true(
    tmp_path, monkeypatch
):
    """Regression guard: epicstaff_common must not accidentally become gated
    behind use_storage the way epicstaff_storage is."""
    import dynamic_venv_executor_chain

    async def _fake_shell(cmd, **kwargs):
        venv_path_str = cmd.strip().split()[-1]
        Path(venv_path_str).mkdir(parents=True, exist_ok=True)
        return _FakeProcess()

    monkeypatch.setattr(
        dynamic_venv_executor_chain.asyncio, "create_subprocess_shell", _fake_shell
    )

    context = _make_context(tmp_path, use_storage=True)
    await CreateVenvHandler().handle(context)

    assert "/app/src/shared/epicstaff_common" in context["libraries"]
    assert "/app/src/shared/epicstaff_storage" in context["libraries"]
