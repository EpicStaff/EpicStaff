"""CreateVenvHandler must install epicstaff_common into every sandbox venv,
unconditionally — unlike epicstaff_storage, which is gated behind
context["use_storage"].

Also covers the fingerprinting allowlist: only the predefined local library
directories may be walked, so a caller-supplied path cannot make the sandbox
read an unbounded tree.
"""

from pathlib import Path
from typing import Any

import pytest

pytest.importorskip(
    "pwd",
    reason="POSIX-only: sandbox isolation requires pwd/landlock; runs in the Linux image",
)

import dynamic_venv_executor_chain
from dynamic_venv_executor_chain import (
    ALLOWED_LOCAL_LIBRARY_PATHS,
    CreateVenvHandler,
    _fingerprint_library,
)


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


@pytest.fixture
def forbid_rglob(monkeypatch):
    """Make any filesystem walk in _fingerprint_library a hard test failure."""

    def _explode(self, pattern):
        raise AssertionError(f"_fingerprint_library scanned {self} (pattern {pattern!r})")

    monkeypatch.setattr(Path, "rglob", _explode)


@pytest.mark.parametrize(
    "library",
    ["/proc/self", "/", ".", "..", "/tmp", "/app/src/shared"],
)
def test_non_allowlisted_directory_is_not_scanned(library, forbid_rglob):
    assert _fingerprint_library(library) == library


@pytest.mark.parametrize("library", ["requests==2.31.0", "numpy>=1.20.0", "pytest"])
def test_pip_spec_passes_through_unchanged(library, forbid_rglob):
    assert _fingerprint_library(library) == library


def test_allowlist_covers_every_predefined_library():
    """Every library CreateVenvHandler installs must be fingerprintable by content."""
    predefined = {
        "/app/src/shared/dotdict",
        "/app/src/shared/epicstaff_secrets",
        "/app/src/shared/epicstaff_common",
        "/app/src/shared/epicstaff_storage",
    }
    assert predefined <= ALLOWED_LOCAL_LIBRARY_PATHS


def test_allowlisted_directory_is_content_hashed(tmp_path, monkeypatch):
    library_path = tmp_path / "dotdict"
    library_path.mkdir()
    (library_path / "module.py").write_text("def hello(): pass")
    monkeypatch.setattr(
        dynamic_venv_executor_chain,
        "ALLOWED_LOCAL_LIBRARY_PATHS",
        frozenset({str(library_path)}),
    )

    fingerprint = _fingerprint_library(str(library_path))

    assert fingerprint != str(library_path)
    assert len(fingerprint) == 64

    (library_path / "module.py").write_text("def hello(): return 1")
    assert _fingerprint_library(str(library_path)) != fingerprint


def test_allowlisted_path_that_is_not_a_directory_passes_through(tmp_path, monkeypatch):
    missing_path = tmp_path / "not_installed"
    monkeypatch.setattr(
        dynamic_venv_executor_chain,
        "ALLOWED_LOCAL_LIBRARY_PATHS",
        frozenset({str(missing_path)}),
    )

    assert _fingerprint_library(str(missing_path)) == str(missing_path)
