"""Stand-in for the uv provider that touches the filesystem but never runs uv.

``apply`` writes a real lock file whose content depends on the library set, because the
build orchestrator derives ``venv.hash`` from a sha256 of those bytes. ``get_lock_file``
and ``get_python_binary`` are inherited from the port, so the paths match production.

``read_resolved_versions`` hands back whatever a test put in ``resolved_versions`` instead
of parsing: the lock dialect is uv's, and ``UVProvider`` is where that parsing is pinned.
"""

from pathlib import Path

from manager.application.ports import AbstractUVProvider
from manager.domain.types import LibraryString

__all__ = ["FakeUVProvider"]


class FakeUVProvider(AbstractUVProvider):
    def __init__(self) -> None:
        self.init_venv_calls: list[Path] = []
        self.apply_calls: list[tuple[Path, tuple[LibraryString, ...]]] = []
        self.install_local_calls: list[tuple[Path, tuple[Path, ...]]] = []
        self.fail_init: Exception | None = None
        self.fail_apply: Exception | None = None
        self.fail_install_local: Exception | None = None
        self.resolved_versions: dict[str, str] = {}

    async def init_venv(self, venv_path: Path) -> None:
        self.init_venv_calls.append(venv_path)
        if self.fail_init is not None:
            raise self.fail_init
        (venv_path / "bin").mkdir(parents=True)
        self.get_python_binary(venv_path).write_text("#!/bin/sh\n")

    async def apply(self, venv_path: Path, *libs: LibraryString) -> None:
        self.apply_calls.append((venv_path, libs))
        if self.fail_apply is not None:
            raise self.fail_apply
        self.get_lock_file(venv_path).write_bytes("\n".join(libs).encode("utf-8"))

    def read_resolved_versions(self, venv_path: Path) -> dict[str, str]:
        return dict(self.resolved_versions)

    async def install_local(self, venv_path: Path, *packages: Path) -> None:
        self.install_local_calls.append((venv_path, packages))
        if self.fail_install_local is not None:
            raise self.fail_install_local
