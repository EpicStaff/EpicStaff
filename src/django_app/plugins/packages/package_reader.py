import struct
import zipfile
from typing import BinaryIO

from epicstaff_plugin.package_layout import (
    MAX_ENTRIES,
    MAX_UNCOMPRESSED_BYTES,
    MIGRATION_PATTERN,
    PackageArchive,
    read_package_file,
)
from epicstaff_plugin.problems import PACKAGE_LOC, PackageProblemsError, Problem
from tables.services.storage_service.archive_unpacking.extraction_guard import (
    ArchiveExtractionGuard,
)
from tables.services.storage_service.archive_unpacking.safe_readers import zip_entry_count

from plugins.exceptions import InvalidPluginError


def read_uploaded_package(file: BinaryIO) -> PackageArchive:
    """Check every package rule on an uploaded `.esplugin` without trusting its headers.

    The central directory is counted before zipfile builds an object per entry, then every
    member streams once through `ArchiveExtractionGuard` with the package caps.

    Raises:
        InvalidPluginError: Every problem found, each located under `package`, `contents`,
            `signature` or `manifest`.
    """
    file.seek(0)
    try:
        if zip_entry_count(file, stop_after=MAX_ENTRIES) > MAX_ENTRIES:
            raise InvalidPluginError([Problem(PACKAGE_LOC, f"has more than {MAX_ENTRIES} entries")])
    except (zipfile.BadZipFile, OSError, ValueError, struct.error):
        raise InvalidPluginError([Problem(PACKAGE_LOC, "is not a zip archive")]) from None
    guard = ArchiveExtractionGuard(max_entries=MAX_ENTRIES, max_total_bytes=MAX_UNCOMPRESSED_BYTES)
    try:
        return read_package_file(file, guard)
    except PackageProblemsError as error:
        raise InvalidPluginError(error.problems) from None


def migration_files(package: PackageArchive) -> list[dict[str, str]]:
    """The package's migration files as `{name, sha256}`, sorted by name.

    The digest is the one `CONTENTS.json` lists, which the reader checked against the bytes:
    the one the plugin node records in the database's migration ledger when it applies them.
    """
    files = []
    for file in package.files:
        if match := MIGRATION_PATTERN.match(file.path):
            files.append({"name": match.group(1), "sha256": file.sha256})
    return sorted(files, key=lambda file: file["name"])
