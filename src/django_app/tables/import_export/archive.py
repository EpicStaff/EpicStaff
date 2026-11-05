"""Zip archives that carry an export envelope together with the files it refers to.

An archive holds `export.json` (the same envelope a plain JSON export has) and the
members it names, such as collection documents and index data. Reading is guarded
against path escapes, links and zip bombs before the import writes anything.
"""

import json
import os
import shutil
import tempfile
import zipfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import BinaryIO, Literal, Self

from django.conf import settings
from rest_framework.exceptions import ValidationError
from src.shared.epicstaff_storage.path_safety import sanitize_storage_path

from tables.services.storage_service.archive_unpacking.extraction_guard import (
    ArchiveExtractionGuard,
    GuardedMemberReader,
)
from tables.services.storage_service.archive_unpacking.safe_readers import zip_entry_count

ENVELOPE_MEMBER = "export.json"
_ZIP_SIGNATURE = b"PK\x03\x04"
_COPY_CHUNK_SIZE = 1024 * 1024
# The upper 16 bits of a zip member's external attributes hold its Unix file mode.
_FILE_TYPE_MASK = 0o170000
_SYMLINK_MODE = 0o120000
_ENCRYPTED_FLAG = 0x1


def detect_file_kind(head: bytes) -> Literal["zip", "json"]:
    """Tell an archive export from a plain JSON export by its first bytes."""
    return "zip" if head.startswith(_ZIP_SIGNATURE) else "json"


@contextmanager
def temporary_archive(fill: Callable[[BinaryIO], None]) -> Iterator[str]:
    """Give the path of a temporary `.zip` that `fill` wrote; delete it afterwards.

    `ImportArchive` reads a file on disk, while an archive arrives as an upload or
    from storage. The file is closed before its path is handed out.
    """
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as file:
        path = file.name
        try:
            fill(file)
        except BaseException:
            file.close()
            os.unlink(path)
            raise
    try:
        yield path
    finally:
        os.unlink(path)


class InvalidArchiveError(ValidationError):
    """The upload is not a zip this import can read safely."""


class ArchiveMemberMissingError(InvalidArchiveError):
    """export.json names a file the archive does not contain."""


def _refuse(reason: str) -> InvalidArchiveError:
    return InvalidArchiveError({"code": "invalid_archive", "detail": reason})


class ExportArchiveWriter:
    """Build an export archive in a temporary file.

    Use it as a context manager. On success the zip is closed and stays at `path`;
    the caller owns it from then on and deletes it. If the block raises, the
    temporary file is deleted.
    """

    def __enter__(self) -> Self:
        self._file = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
        self._zip = zipfile.ZipFile(
            self._file, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True
        )
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self._zip.close()
        self._file.close()
        if exc_type is not None:
            os.unlink(self._file.name)

    @property
    def path(self) -> str:
        return self._file.name

    def add_bytes(self, member: str, data: bytes) -> None:
        self._zip.writestr(member, data)

    def add_file(self, member: str, source: BinaryIO) -> None:
        """Copy `source` into the archive in chunks, never holding it whole in memory."""
        # zipfile cannot know the size up front here; without ZIP64 a member past 2 GiB fails.
        with self._zip.open(member, "w", force_zip64=True) as target:
            shutil.copyfileobj(source, target, _COPY_CHUNK_SIZE)

    def write_envelope(self, envelope: dict) -> None:
        self.add_bytes(ENVELOPE_MEMBER, json.dumps(envelope).encode())


class ImportArchive:
    """An uploaded export archive whose members have all been checked.

    Create it with `ImportArchive.open`, which refuses an unsafe archive before
    anything is read from it. Every byte read through `open_member` also counts
    against one size cap for the whole archive, so a member that holds more than
    its declared size still stops the import.
    """

    def __init__(self, file: BinaryIO, zip_file: zipfile.ZipFile, guard: ArchiveExtractionGuard):
        self._file = file
        self._zip = zip_file
        self._guard = guard
        self._names = {info.filename for info in zip_file.infolist() if not info.is_dir()}

    @classmethod
    def open(cls, path: str) -> Self:
        """Open the archive at `path` and check every member before returning.

        Raises:
            InvalidArchiveError: The file is not a zip, or it has too many entries,
                an unsafe or duplicate member name, a link, an encrypted member, a
                total unpacked size past the cap, or no `export.json`.
        """
        # ImportArchive owns the file from here and closes it in close().
        file = open(path, "rb")  # noqa: SIM115
        try:
            # Counts the real central directory, so a false declared total cannot hide entries.
            entry_count = zip_entry_count(file, stop_after=settings.MAX_KNOWLEDGE_ARCHIVE_ENTRIES)
            if entry_count > settings.MAX_KNOWLEDGE_ARCHIVE_ENTRIES:
                raise _refuse(f"more than {settings.MAX_KNOWLEDGE_ARCHIVE_ENTRIES} entries")
            zip_file = zipfile.ZipFile(file)
        except zipfile.BadZipFile as error:
            file.close()
            raise _refuse("not a zip archive") from error
        except BaseException:
            file.close()
            raise

        try:
            cls._validate_members(zip_file)
        except BaseException:
            zip_file.close()
            file.close()
            raise

        guard = ArchiveExtractionGuard(
            max_entries=settings.MAX_KNOWLEDGE_ARCHIVE_ENTRIES,
            max_total_bytes=settings.MAX_KNOWLEDGE_ARCHIVE_UNCOMPRESSED_SIZE,
        )
        return cls(file, zip_file, guard)

    @staticmethod
    def _validate_members(zip_file: zipfile.ZipFile) -> None:
        seen_names: set[str] = set()
        total_size = 0
        for info in zip_file.infolist():
            if info.is_dir():
                continue
            try:
                safe_name = sanitize_storage_path(info.filename, allow_empty=False)
            except ValueError as error:
                raise _refuse(f"unsafe member name {info.filename!r}") from error
            # A name the check had to normalize (such as "a/./b") is refused, not renamed.
            if safe_name != info.filename:
                raise _refuse(f"unsafe member name {info.filename!r}")
            if (info.external_attr >> 16) & _FILE_TYPE_MASK == _SYMLINK_MODE:
                raise _refuse(f"member {info.filename!r} is a link")
            if info.flag_bits & _ENCRYPTED_FLAG:
                raise _refuse(f"member {info.filename!r} is encrypted")
            if info.filename in seen_names:
                raise _refuse(f"member {info.filename!r} appears twice")
            # zipfile stops reading a member at its declared size, so the declared sizes
            # are a safe upper bound of what the import can unpack.
            total_size += info.file_size
            if total_size > settings.MAX_KNOWLEDGE_ARCHIVE_UNCOMPRESSED_SIZE:
                raise _refuse(
                    f"unpacks to more than {settings.MAX_KNOWLEDGE_ARCHIVE_UNCOMPRESSED_SIZE} bytes"
                )
            seen_names.add(info.filename)

        if ENVELOPE_MEMBER not in seen_names:
            raise _refuse(f"{ENVELOPE_MEMBER} is missing")

    def envelope(self) -> dict:
        """Return the parsed `export.json`.

        Raises:
            InvalidArchiveError: `export.json` is not valid UTF-8 JSON.
        """
        with self.open_member(ENVELOPE_MEMBER) as member:
            data = member.read()
        try:
            return json.loads(data)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise _refuse(f"{ENVELOPE_MEMBER} is not valid JSON") from error

    def open_member(self, member: str) -> GuardedMemberReader:
        """Open one member for reading; close it before opening the next large one.

        Raises:
            ArchiveMemberMissingError: The archive has no member with this name.
        """
        if member not in self._names:
            raise ArchiveMemberMissingError({"code": "archive_member_missing", "detail": member})
        return GuardedMemberReader(self._zip.open(member), self._guard, member)

    def close(self) -> None:
        self._zip.close()
        self._file.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()
