import abc
from pathlib import Path

from manager.domain.types import LibraryString


class AbstractUVProvider(abc.ABC):
    @classmethod
    @abc.abstractmethod
    async def init_venv(cls, venv_path: Path):
        pass

    @classmethod
    @abc.abstractmethod
    async def apply(cls, venv_path: Path, *libs: LibraryString):
        pass

    @classmethod
    @abc.abstractmethod
    async def install_local(cls, venv_path: Path, *packages: Path):
        """Install local source packages (by directory path) into the venv."""

    @staticmethod
    def get_python_binary(venv_path: Path) -> Path:
        return venv_path / "bin/python"

    @staticmethod
    def get_lock_file(venv_path: Path) -> Path:
        return venv_path / "dependencies.lock"
