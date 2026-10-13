"""Which venv an execution gets: venvs are cached by a hash of their libraries.

The same libraries must reuse the same venv, any real change must get a fresh one,
and only the predefined local libraries may be walked to hash their content - a
library entry comes from user-authored node metadata, so walking any directory it
names would let a caller point the sandbox at "/" or "/proc/self".
"""

import asyncio
from pathlib import Path

import pytest

pytest.importorskip(
    "pwd",
    reason="POSIX-only: sandbox isolation requires pwd/landlock; runs in the Linux image",
)

import dynamic_venv_executor_chain
from dynamic_venv_executor_chain import ALLOWED_LOCAL_LIBRARY_PATHS, CreateVenvHandler


class _FakeProcess:
    returncode = 0

    async def communicate(self):
        return (b"", b"")


@pytest.fixture(autouse=True)
def venv_creation_is_faked(monkeypatch):
    async def _create_venv(cmd, **kwargs):
        Path(cmd.strip().split()[-1]).mkdir(parents=True, exist_ok=True)
        return _FakeProcess()

    monkeypatch.setattr(dynamic_venv_executor_chain.asyncio, "create_subprocess_shell", _create_venv)


@pytest.fixture
def trusted_local_libraries(monkeypatch):
    """Let a test treat its own tmp_path directories as predefined local libraries."""

    def _trust(*paths: Path) -> None:
        monkeypatch.setattr(
            dynamic_venv_executor_chain,
            "ALLOWED_LOCAL_LIBRARY_PATHS",
            frozenset(str(path) for path in paths),
        )

    return _trust


def _venv_for(tmp_path: Path, libraries: list[str]) -> Path:
    context = {"libraries": list(libraries), "base_venv_path": tmp_path / "venvs"}
    asyncio.run(CreateVenvHandler().handle(context))
    return context["venv_path"]


def _local_library(tmp_path: Path, name: str = "my_lib") -> Path:
    library = tmp_path / name
    library.mkdir()
    (library / "module.py").write_text("def foo(): pass")
    (library / "sub").mkdir()
    (library / "sub" / "data.json").write_text('{"key": "value"}')
    return library


def test_same_libraries_reuse_the_same_venv_in_any_order(tmp_path, trusted_local_libraries):
    library = _local_library(tmp_path)
    trusted_local_libraries(library)

    first = _venv_for(tmp_path, [str(library), "requests==2.28.0"])

    assert _venv_for(tmp_path, ["requests==2.28.0", str(library)]) == first


def test_a_changed_pip_spec_gets_a_new_venv(tmp_path):
    assert _venv_for(tmp_path, ["requests==2.28.0"]) != _venv_for(tmp_path, ["requests==2.29.0"])


def test_changed_local_library_content_gets_a_new_venv(tmp_path, trusted_local_libraries):
    library = _local_library(tmp_path)
    trusted_local_libraries(library)
    before = _venv_for(tmp_path, [str(library)])

    (library / "module.py").write_text("def foo(): return 1")

    assert _venv_for(tmp_path, [str(library)]) != before


def test_build_artifacts_in_a_local_library_keep_the_same_venv(tmp_path, trusted_local_libraries):
    library = _local_library(tmp_path)
    trusted_local_libraries(library)
    before = _venv_for(tmp_path, [str(library)])

    for artifact in (
        ".venv/pyvenv.cfg",
        "__pycache__/module.cpython-312.pyc",
        ".pytest_cache/last_run.json",
        ".git/config",
        "my_lib.egg-info/PKG-INFO",
    ):
        (library / artifact).parent.mkdir(parents=True, exist_ok=True)
        (library / artifact).write_text("generated")

    assert _venv_for(tmp_path, [str(library)]) == before


def test_an_unreadable_file_is_skipped_rather_than_failing(
    tmp_path, monkeypatch, trusted_local_libraries
):
    library = _local_library(tmp_path)
    readable_twin = _local_library(tmp_path, "twin")
    trusted_local_libraries(library, readable_twin)
    unreadable = library / "secret.py"
    unreadable.write_text("unreadable")
    real_read_bytes = Path.read_bytes

    def read_bytes(path):
        if path == unreadable:
            raise OSError("Permission denied")
        return real_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", read_bytes)

    assert _venv_for(tmp_path, [str(library)]) == _venv_for(tmp_path, [str(readable_twin)])


@pytest.mark.parametrize("library", ["/proc/self", "/", ".", "..", "/tmp", "/app/src/shared"])
def test_a_directory_outside_the_predefined_libraries_is_never_walked(
    tmp_path, monkeypatch, library
):
    def _explode(self, pattern):
        raise AssertionError(f"walked {self} (pattern {pattern!r})")

    monkeypatch.setattr(Path, "rglob", _explode)

    _venv_for(tmp_path, [library])


def test_every_predefined_library_is_hashed_by_content():
    """Every library CreateVenvHandler installs must be on the walk allowlist."""
    predefined = {
        "/app/src/shared/dotdict",
        "/app/src/shared/epicstaff_secrets",
        "/app/src/shared/epicstaff_common",
        "/app/src/shared/epicstaff_storage",
    }
    assert predefined <= ALLOWED_LOCAL_LIBRARY_PATHS
