"""Stand-in for the uv provider that touches the filesystem but never runs uv.

``apply`` writes a real lock file whose content depends on the library set, because the
build orchestrator derives ``venv.hash`` from a sha256 of those bytes. ``get_lock_file``
and ``get_python_binary`` are inherited from the port, so the paths match production.

``read_resolved_versions`` hands back whatever a test put in ``resolved_versions`` instead
of parsing: the lock dialect is uv's, and ``UVProvider`` is where that parsing is pinned.

``build_wheel`` keeps the one rule real uv applies before it builds anything -- a directory
holding neither ``pyproject.toml`` nor ``setup.py`` "does not appear to be a Python project"
-- so a caller that hands it the wrong directory fails here the way it would in production.
"""

from pathlib import Path

from manager.application.ports import AbstractUVProvider
from manager.application.ports.errors import EnvironmentBuildError
from manager.domain.types import LibraryString

__all__ = ["FakeUVProvider"]


class FakeUVProvider(AbstractUVProvider):
    def __init__(self) -> None:
        self.init_venv_calls: list[Path] = []
        self.apply_calls: list[tuple[Path, tuple[LibraryString, ...]]] = []
        self.wheelhouses: list[Path | None] = []
        self.wheelhouse_contents: list[list[str]] = []
        self.install_local_calls: list[tuple[Path, tuple[Path, ...]]] = []
        self.build_wheel_calls: list[tuple[Path, Path]] = []
        self.fail_init: Exception | None = None
        self.fail_apply: Exception | None = None
        self.fail_install_local: Exception | None = None
        self.fail_build_wheel: Exception | None = None
        self.resolved_versions: dict[str, str] = {}
        self.built_wheel_name = "fake_library-1.0.0-py3-none-any.whl"

    async def init_venv(self, venv_path: Path) -> None:
        self.init_venv_calls.append(venv_path)
        if self.fail_init is not None:
            raise self.fail_init
        (venv_path / "bin").mkdir(parents=True)
        self.get_python_binary(venv_path).write_text("#!/bin/sh\n")

    async def apply(
        self, venv_path: Path, *libs: LibraryString, wheelhouse: Path | None = None
    ) -> None:
        self.apply_calls.append((venv_path, libs))
        self.wheelhouses.append(wheelhouse)
        # Read now, not handed back as a path: the wheelhouse is a temporary directory
        # that is gone by the time a test looks, so what was in it is recorded here.
        self.wheelhouse_contents.append(
            sorted(path.name for path in wheelhouse.iterdir()) if wheelhouse else []
        )
        if self.fail_apply is not None:
            raise self.fail_apply
        self.get_lock_file(venv_path).write_bytes("\n".join(libs).encode("utf-8"))

    def read_resolved_versions(self, venv_path: Path) -> dict[str, str]:
        return dict(self.resolved_versions)

    async def install_local(self, venv_path: Path, *packages: Path) -> None:
        self.install_local_calls.append((venv_path, packages))
        if self.fail_install_local is not None:
            raise self.fail_install_local

    async def build_wheel(self, source_dir: Path, output_dir: Path) -> Path:
        self.build_wheel_calls.append((source_dir, output_dir))
        if self.fail_build_wheel is not None:
            raise self.fail_build_wheel
        if not (source_dir / "pyproject.toml").is_file() and not (source_dir / "setup.py").is_file():
            raise EnvironmentBuildError(
                f"`{source_dir}` does not appear to be a Python project, as neither "
                "`pyproject.toml` nor `setup.py` are present in the directory"
            )
        output_dir.mkdir(parents=True, exist_ok=True)
        wheel = output_dir / self.built_wheel_name
        wheel.write_bytes(b"PK\x03\x04 fake wheel")
        return wheel
