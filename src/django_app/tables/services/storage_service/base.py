import zipfile
from abc import ABC, abstractmethod
from collections.abc import Iterator

from tables.services.storage_service.archive_limits import (
    ArchiveExtractionGuard,
    GuardedMemberReader,
    default_guard,
)
from tables.services.storage_service.archive_readers import is_tar, open_tar
from tables.services.storage_service.dataclasses import (
    FileInfo,
    FileListItem,
    FolderInfo,
    TreeNode,
    UploadResult,
)
from tables.services.storage_service.path_utils import sanitize_storage_path


class AbstractStorageBackend(ABC):
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

    def _sanitize_archive_member_name(self, name: str) -> str:
        """Raise ValueError if an archive member name can escape the extraction folder."""
        return sanitize_storage_path(name, allow_empty=False)

    def iter_archive_members_streaming(
        self, archive_file, guard: ArchiveExtractionGuard | None = None
    ) -> Iterator[tuple[str, "GuardedMemberReader"]]:
        """Yield (safe_name, GuardedMemberReader) per file member, streaming.

        Rejects symlinks, hardlinks and any tar member that is not a plain file or
        folder (every tar member, folders too, counts toward the guard's entry
        cap) and sanitizes names, but does not read member bytes here — the
        caller streams each reader to storage before advancing to the next
        member (member stays open during the yield)."""
        pos = archive_file.tell()
        guard = guard or default_guard()

        if zipfile.is_zipfile(archive_file):
            archive_file.seek(pos)

            with zipfile.ZipFile(archive_file, "r") as zf:
                for entry in zf.infolist():
                    if entry.is_dir():
                        continue
                    guard.account_entry()
                    safe_name = self._sanitize_archive_member_name(entry.filename)
                    with zf.open(entry, "r") as member_file:
                        yield safe_name, GuardedMemberReader(member_file, guard, entry.filename)
            return

        archive_file.seek(pos)

        if is_tar(archive_file):
            with open_tar(archive_file) as tf:
                # Lazily, not getmembers(): that inflates the whole archive first.
                for member in tf:
                    guard.account_entry()
                    if member.issym() or member.islnk():
                        raise ValueError(
                            f"Archive member is a symlink or hardlink: {member.name!r}"
                        )
                    if member.isdir():
                        continue
                    if not member.isfile() or member.issparse():
                        raise ValueError(
                            f"Archive member is not a plain file or folder: {member.name!r}"
                        )
                    safe_name = self._sanitize_archive_member_name(member.name)
                    fobj = tf.extractfile(member)
                    if fobj:
                        yield safe_name, GuardedMemberReader(fobj, guard, member.name)
            return

        archive_file.seek(pos)
        raise ValueError("Unsupported archive format — expected ZIP or TAR")

    @abstractmethod
    def list_(self, prefix: str) -> list[FileListItem]:
        """List files and folders at prefix."""

    @abstractmethod
    def upload(self, path: str, file_object) -> UploadResult:
        """Upload file_object to path."""

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
