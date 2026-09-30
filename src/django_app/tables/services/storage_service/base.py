from abc import ABC, abstractmethod

from tables.services.storage_service.dataclasses import (
    FileInfo,
    FileListItem,
    FolderInfo,
    TreeNode,
)
from utils.logger import logger


class StorageUnreachable(Exception):  # noqa: N818
    """The object store is unreachable, timed out or failed on its side."""


class AbstractStorageBackend(ABC):
    """Object storage of flat keys, where a key ending in "/" is a folder marker.
    Only the streaming-upload methods raise StorageUnreachable on an outage."""

    @staticmethod
    def _increment_name(name: str, is_folder: bool = False) -> str:
        """
        Increment a copy-suffix on a name.

        file.txt   -> file (1).txt -> file (2).txt
        folder     -> folder (1)   -> folder (2)
        """
        if is_folder:
            base, counter = name, 0
            if base.endswith(")") and " (" in base:
                prefix, _, num = base[:-1].rpartition(" (")
                if num.isdigit():
                    base, counter = prefix, int(num)
            return f"{base} ({counter + 1})"

        stem, dot, ext = name.rpartition(".")
        if not dot:
            stem, ext = name, ""
        else:
            ext = dot + ext

        counter = 0
        if stem.endswith(")") and " (" in stem:
            prefix, _, num = stem[:-1].rpartition(" (")
            if num.isdigit():
                stem, counter = prefix, int(num)
        return f"{stem} ({counter + 1}){ext}"

    @abstractmethod
    def list_(self, prefix: str) -> list[FileListItem]:
        """List files and folders at prefix."""

    @property
    @abstractmethod
    def part_size(self) -> int:
        """Bytes per part of upload_chunks and upload_stream; callers size buffers by it."""

    @abstractmethod
    async def upload_chunks(self, path: str, chunks, *, size_guard=None, before_commit=None) -> int:
        """Store an async stream of byte chunks at path; return the byte count.
        `before_commit(total)` runs before the object becomes visible; raising aborts the upload."""

    @abstractmethod
    def upload_stream(self, path: str, file_object) -> None:
        """Store a readable of unknown size at path; read(n) must return n bytes until EOF."""

    @abstractmethod
    def put_bytes(self, path: str, data: bytes) -> int:
        """Store data at path in one request; returns its size."""

    @abstractmethod
    def download(self, path: str) -> bytes:
        """Return file content as bytes."""

    @abstractmethod
    def download_range(self, path: str, first: int, last: int | None) -> tuple[bytes, str]:
        """Return bytes first..last (inclusive; None = to the end) and their Content-Range."""

    @abstractmethod
    def unique_key(self, key: str, is_folder: bool = False) -> str:
        """Return key or its first free "name (n)" variant; a folder also clashes with a file."""

    @abstractmethod
    def delete(self, path: str) -> None:
        """Delete file or folder (folder = recursive)."""

    @abstractmethod
    def delete_prefix(self, prefix: str) -> None:
        """Delete every object under prefix, including any folder marker keyed as the prefix itself."""

    @abstractmethod
    def mkdir(self, path: str) -> None:
        """Create a folder."""

    @abstractmethod
    def claim_folder(self, path: str) -> bool:
        """Atomically create the folder marker if nothing of that name exists; False if taken."""

    @abstractmethod
    def move(self, source_path: str, destination_path: str) -> str:
        """
        Move source into the destination folder (never overwrites destination_path
        itself — source is placed as a child of it).

        Returns the actual destination base created after name-dedup: the exact
        new file key for a file, or the folder base path (ending in "/") for a
        folder.
        """

    @abstractmethod
    def rename(self, source_path: str, destination_path: str) -> None:
        """
        Rename/move source to the exact destination path (never into it).

        Raises FileExistsError when a file or folder already exists at the
        exact destination path.
        """

    @abstractmethod
    def copy(self, source_path: str, destination_path: str) -> list[tuple[str, int]]:
        """Copy a file or folder into the destination folder; return (key, size) per created object.
        On failure nothing it created is left behind."""

    @abstractmethod
    def delete_keys(self, keys: list[str]) -> None:
        """Delete exactly these keys (as copy returns them), nothing else."""

    def discard_keys(self, keys: list[str]) -> None:
        """Best-effort removal of the keys a failed write created; failures are only logged."""
        if not keys:
            return
        try:
            # One key twice (a name repeated in an archive) is deleted once.
            self.delete_keys(list(dict.fromkeys(keys)))
        except Exception:
            logger.exception("Could not remove {} objects of a failed write", len(keys))

    @abstractmethod
    def info(self, path: str) -> FileInfo | FolderInfo:
        """Return file or folder metadata."""

    @abstractmethod
    def head_file(self, path: str) -> FileInfo | None:
        """Metadata of the file at path from one quick, non-retried request, or None."""

    @abstractmethod
    def exists(self, path: str) -> bool:
        """Return True if the path exists."""

    @abstractmethod
    def list_all_keys(self, prefix: str) -> list[str]:
        """Recursively list all file keys under prefix (excludes folder markers)."""

    @abstractmethod
    def list_tree(
        self, prefix: str, max_depth: int | None = None, max_entries: int = 50_000
    ) -> tuple[TreeNode, bool]:
        """Return (root_node, truncated). Root path ends with '/'."""

    @abstractmethod
    def list_all_objects(self, prefix: str) -> list[tuple[str, int, str]]:
        """
        Recursively list all file objects under prefix.

        Returns a list of (key, size, modified_iso) tuples where:
          - key: full storage key as returned by the backend (not stripped)
          - size: file size in bytes
          - modified_iso: ISO-8601 datetime string (UTC)

        Folder marker keys (ending in '/') and '.keep' files are excluded.
        """
