import abc
from pathlib import Path

from manager.domain.types import LibraryString


class AbstractUVProvider(abc.ABC):
    """Builds a venv's environment.

    A build step that fails raises an `EnvironmentBuildError` from
    `manager.application.ports.errors`, or one of its subclasses when the cause names a
    declared package.
    """

    @classmethod
    @abc.abstractmethod
    async def init_venv(cls, venv_path: Path):
        """Create an empty venv at `venv_path`.

        Raises:
            EnvironmentBuildError: The venv could not be created.
        """

    @classmethod
    @abc.abstractmethod
    async def apply(cls, venv_path: Path, *libs: LibraryString):
        """Resolve `libs`, write the lock file, and install exactly what it pins.

        Raises:
            PackageNotFoundError: A declared package does not exist.
            PackageVersionNotFoundError: A declared package has no version matching
                its specification.
            DependencyConflictError: A declared package needs dependency versions that
                conflict with the other declared packages.
            EnvironmentBuildError: Any other failure.
        """

    @classmethod
    @abc.abstractmethod
    async def install_local(cls, venv_path: Path, *packages: Path):
        """Install local source packages (by directory path) into the venv.

        Raises:
            EnvironmentBuildError: The packages could not be installed.
        """

    @classmethod
    @abc.abstractmethod
    def read_resolved_versions(cls, venv_path: Path) -> dict[str, str]:
        """Return the version resolved for every library, keyed by canonical name.

        A venv with no lock file resolves nothing.
        """

    @staticmethod
    def get_python_binary(venv_path: Path) -> Path:
        return venv_path / "bin/python"

    @staticmethod
    def get_lock_file(venv_path: Path) -> Path:
        return venv_path / "dependencies.lock"
