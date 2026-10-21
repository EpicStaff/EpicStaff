"""CreateVenvHandler installs the shared libraries into every sandbox venv, and
epicstaff_storage only when the job was given storage access."""

from pathlib import Path
from typing import Any

import pytest

pytest.importorskip(
    "pwd",
    reason="POSIX-only: sandbox isolation requires pwd/landlock; runs in the Linux image",
)

import dynamic_venv_executor_chain
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
@pytest.mark.parametrize(
    ("overrides", "with_storage_library"),
    [({}, False), ({"use_storage": False}, False), ({"use_storage": True}, True)],
    ids=["use-storage-absent", "use-storage-false", "use-storage-true"],
)
async def test_every_venv_gets_the_shared_libraries_and_storage_only_when_asked(
    tmp_path, monkeypatch, overrides, with_storage_library
):
    """dotdict and epicstaff_secrets are imported by every wrapped job; if secrets were
    conditional, an undeclared secret would surface as an ImportError instead."""

    async def _fake_shell(cmd, **kwargs):
        Path(cmd.strip().split()[-1]).mkdir(parents=True, exist_ok=True)
        return _FakeProcess()

    monkeypatch.setattr(dynamic_venv_executor_chain.asyncio, "create_subprocess_shell", _fake_shell)
    context = _make_context(tmp_path, libraries=["requests"], **overrides)

    await CreateVenvHandler().handle(context)

    assert {
        "requests",
        "/app/src/shared/dotdict",
        "/app/src/shared/epicstaff_secrets",
        "/app/src/shared/epicstaff_common",
    } <= set(context["libraries"])
    assert ("/app/src/shared/epicstaff_storage" in context["libraries"]) is with_storage_library
