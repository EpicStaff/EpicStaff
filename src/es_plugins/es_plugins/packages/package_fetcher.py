import asyncio
import hashlib
from collections.abc import Iterable
from pathlib import Path

from src.shared.models.plugin_nodes import DesiredPackage

from es_plugins.agent.django_client import DjangoNodeClient

_HASH_CHUNK_BYTES = 1024 * 1024


class PackageFetcher:
    """Downloads packages into the agent's downloads directory, keeping each for reuse.

    A package is kept under its id and sha256 until it is no longer in the desired state, so
    a restarted node does not download it again.
    """

    def __init__(self, client: DjangoNodeClient, downloads_directory: Path):
        self._client = client
        self._downloads_directory = downloads_directory

    def path_for(self, package: DesiredPackage) -> Path:
        return self._downloads_directory / f"{package.package_id}-{package.sha256}.esplugin"

    def holds(self, package: DesiredPackage) -> bool:
        """Whether a copy is kept already, so `fetch` may not need to download (it re-checks it)."""
        return self.path_for(package).exists()

    async def fetch(self, package: DesiredPackage) -> Path:
        """Return the local copy of `package`, downloading it unless a matching copy exists.

        Raises:
            NodeApiError: The download failed or did not match the desired state.
        """
        path = self.path_for(package)
        if path.exists() and await asyncio.to_thread(_sha256_of, path) == package.sha256:
            return path
        await self._client.download_package(package, path)
        return path

    def prune(self, keep: Iterable[DesiredPackage]) -> None:
        """Delete every downloaded package except those in `keep`."""
        kept = {self.path_for(package).name for package in keep}
        for path in self._downloads_directory.glob("*.esplugin"):
            if path.name not in kept:
                path.unlink(missing_ok=True)


def _sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as package_file:
        while chunk := package_file.read(_HASH_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()
