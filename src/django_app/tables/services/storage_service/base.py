import posixpath
import tarfile
import zipfile
from abc import ABC, abstractmethod
from typing import Iterator

from tables.services.storage_service.dataclasses import (
    FileInfo,
    FolderInfo,
    FileListItem,
    TreeNode,
    UploadResult,
)


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

    def _check_archive_password(self, archive_file, archive_name: str) -> None:
        """Raise ValueError if archive contains any password-protected entries."""
        pos = archive_file.tell()
        is_zip = zipfile.is_zipfile(archive_file)
        archive_file.seek(pos)
        if not is_zip:
            return

        msg = f"Archive '{archive_name}' contains protected files"
        try:
            with zipfile.ZipFile(archive_file, "r") as zf:
                for entry in zf.infolist():
                    if not entry.is_dir() and entry.flag_bits & 0x1:
                        raise ValueError(msg)
        except (RuntimeError, zipfile.BadZipFile):
            raise ValueError(msg)
        finally:
            archive_file.seek(pos)

    def _sanitize_archive_member_name(self, name: str) -> str:
        """Raise ValueError if an archive member name can escape the extraction folder."""
        if not name:
            raise ValueError("Archive member has an empty name")

        if "\x00" in name:
            raise ValueError(f"Archive member name contains a null byte: {name!r}")

        normalized = posixpath.normpath(name.replace("\\", "/"))

        if (
            posixpath.isabs(normalized)
            or normalized.startswith("/")
            or normalized == ".."
            or normalized.startswith("../")
        ):
            raise ValueError(f"Archive member name escapes the target folder: {name!r}")

        return normalized

    def _iter_archive_entries(self, archive_file) -> Iterator[tuple[str, bytes]]:
        """Yield (relative_path, bytes) for every file inside a ZIP or TAR archive."""
        pos = archive_file.tell()

        if zipfile.is_zipfile(archive_file):
            archive_file.seek(pos)

            with zipfile.ZipFile(archive_file, "r") as zf:
                for entry in zf.infolist():
                    if not entry.is_dir():
                        safe_name = self._sanitize_archive_member_name(entry.filename)
                        yield safe_name, zf.read(entry.filename)

            return

        archive_file.seek(pos)

        try:
            is_tar = tarfile.is_tarfile(archive_file)
        except Exception:
            is_tar = False

        if is_tar:
            archive_file.seek(pos)

            with tarfile.open(fileobj=archive_file, mode="r:*") as tf:
                for member in tf.getmembers():
                    if member.issym() or member.islnk():
                        raise ValueError(
                            f"Archive member is a symlink or hardlink: {member.name!r}"
                        )
                    if member.isfile():
                        safe_name = self._sanitize_archive_member_name(member.name)
                        fobj = tf.extractfile(member)
                        if fobj:
                            yield safe_name, fobj.read()

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
    def delete(self, path: str) -> None:
        """Delete file or folder (folder = recursive)."""

    @abstractmethod
    def mkdir(self, path: str) -> None:
        """Create a folder."""

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
    def copy(self, source_path: str, destination_path: str) -> list[str]:
        """Copy file or folder. Returns the actual destination path(s) created."""

    @abstractmethod
    def info(self, path: str) -> FileInfo | FolderInfo:
        """Return file or folder metadata."""

    @abstractmethod
    def exists(self, path: str) -> bool:
        """Return True if the path exists."""

    @abstractmethod
    def list_all_keys(self, prefix: str) -> list[str]:
        """Recursively list all file keys under prefix (excludes folder markers)."""

    @abstractmethod
    def upload_archive(self, prefix: str, archive_file, archive_name: str) -> list[str]:
        """Extract archive into prefix. Returns list of extracted paths."""

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
