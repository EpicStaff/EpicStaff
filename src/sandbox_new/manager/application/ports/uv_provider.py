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
    async def apply(
        cls,
        venv_path: Path,
        *libs: LibraryString,
        wheelhouse: Path | None = None,
        offline: bool = False,
    ):
        """Resolve `libs` into a lock file and install them into the venv.

        Args:
            venv_path: The venv to install into.
            libs: One requirement per entry, written as a package index would read it.
            wheelhouse: A directory of wheels to resolve against as well as the package
                index, for libraries this installation stores itself and no index has.
            offline: Resolve and install from `wheelhouse` alone, without the package
                index or the network.
        """

    @classmethod
    @abc.abstractmethod
    async def install_local(cls, venv_path: Path, *packages: str, wheelhouse: Path):
        """Install `packages` into the venv from `wheelhouse` alone, without the network.

        Args:
            venv_path: The venv to install into.
            packages: Distribution names, each with its wheel in `wheelhouse`.
            wheelhouse: A directory holding the wheels of `packages` and of all their
                dependencies; a missing one fails the install instead of being fetched.
        """

    @classmethod
    @abc.abstractmethod
    def read_resolved_versions(cls, venv_path: Path) -> dict[str, str]:
        """Return the version resolved for every library, keyed by canonical name.

        A venv with no lock file resolves nothing.
        """

    @classmethod
    @abc.abstractmethod
    async def build_wheel(cls, source_dir: Path, output_dir: Path) -> Path:
        """Build the source tree at `source_dir` into a wheel under `output_dir`.

        Args:
            source_dir: Directory holding the unpacked source distribution.
            output_dir: Directory the wheel is written to. Expected to be empty, so
                that the build's own output is the only wheel in it.

        Returns:
            Path of the wheel that was built.

        Raises:
            UVBuildError: The source could not be built, or produced no wheel.
        """

    @staticmethod
    def get_python_binary(venv_path: Path) -> Path:
        return venv_path / "bin/python"

    @staticmethod
    def get_lock_file(venv_path: Path) -> Path:
        return venv_path / "dependencies.lock"
