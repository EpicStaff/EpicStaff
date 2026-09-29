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

    Only the streaming-upload methods (upload_chunks, upload_stream, put_bytes,
    unique_key, claim_folder, mkdir, delete_keys) raise StorageUnreachable on an
    outage, so their callers can tell an outage from a bug without knowing the
    store's client library. The other methods raise whatever the store's client
    raises."""

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
        """Bytes per part of upload_chunks and upload_stream, so each holds about one
        part in memory; callers size what they keep in memory by it too."""

    @abstractmethod
    async def upload_chunks(self, path: str, chunks, *, size_guard=None, before_commit=None) -> int:
        """Store an async stream of byte chunks at path; returns the byte count.

        Holds about one part_size in memory. size_guard(total) is called as bytes
        arrive and raises to stop. `await before_commit(total)` runs once every byte
        is in the store but before the object becomes visible: if it raises, the
        upload is aborted and an object already at path stays untouched."""

    @abstractmethod
    def upload_stream(self, path: str, file_object) -> None:
        """Store a readable of unknown size at path, holding about one part_size in
        memory. file_object.read(n) must return n bytes until EOF."""

    @abstractmethod
    def put_bytes(self, path: str, data: bytes) -> int:
        """Store data at path in one request; returns its size."""

    @abstractmethod
    def download(self, path: str) -> bytes:
        """Return file content as bytes."""

    @abstractmethod
    def download_range(self, path: str, first: int, last: int | None) -> tuple[bytes, str]:
        """Bytes first..last (inclusive; None = to the end) and their Content-Range, taken
        from the stored object itself. RangeNotSatisfiable if first is past its end."""

    @abstractmethod
    def unique_key(self, key: str, is_folder: bool = False) -> str:
        """key, or its first "name (n)" variant that nothing exists at yet. For a
        folder, a file of the same name counts as existing: nothing can be written
        under it."""

    @abstractmethod
    def delete(self, path: str) -> None:
        """Delete file or folder (folder = recursive)."""

    @abstractmethod
    def mkdir(self, path: str) -> None:
        """Create a folder."""

    @abstractmethod
    def claim_folder(self, path: str) -> bool:
        """Create the folder marker only if none exists yet, atomically in the store.
        False when another writer got there first, with a folder or a file of that
        name."""

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
        """Copy file or folder into the destination folder. Returns (key, size) of
        every object created, sizes read from the store; folder markers end in "/".
        On failure nothing it created is left behind."""

    @abstractmethod
    def delete_keys(self, keys: list[str]) -> None:
        """Delete exactly these keys (as copy returns them), nothing else."""

    def discard_keys(self, keys: list[str]) -> None:
        """Best-effort removal of the keys a failed write created. A failure is only
        logged, so the caller re-raises the error that made the write fail."""
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
        """Metadata of the file at path from one quick, non-retried request; None when
        no file is there. For callers that must not stall on a slow store."""

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
