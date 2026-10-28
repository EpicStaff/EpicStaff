"""Deterministic package archives: the same files always give the same bytes."""

import os
import secrets
import shutil
import zipfile
from collections.abc import Callable, Iterable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
FILE_MODE = 0o100644
_UNIX_CREATOR = 3
_COPY_CHUNK_BYTES = 1024 * 1024


@dataclass(frozen=True)
class ArchiveEntry:
    """A file to write into a package: its path in the archive and how to read it."""

    path: str
    open: Callable[[], AbstractContextManager[BinaryIO]]


def write_package(destination: Path, entries: Iterable[ArchiveEntry]) -> None:
    """Write `entries` to `destination` as a deterministic zip, replacing it atomically.

    Entries are sorted by path; every entry gets the 1980-01-01 00:00:00 timestamp, mode
    0644 and deflate compression, so the bytes depend only on the files' paths and content.
    """
    temporary = destination.with_name(f".{destination.name}.{secrets.token_hex(4)}.tmp")
    try:
        with zipfile.ZipFile(temporary, "w") as archive:
            for entry in sorted(entries, key=lambda entry: entry.path):
                info = zipfile.ZipInfo(entry.path, date_time=ZIP_TIMESTAMP)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = _UNIX_CREATOR
                info.external_attr = FILE_MODE << 16
                with entry.open() as source, archive.open(info, "w") as target:
                    shutil.copyfileobj(source, target, _COPY_CHUNK_BYTES)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
