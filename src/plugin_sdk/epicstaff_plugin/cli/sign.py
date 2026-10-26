"""`epicstaff-plugin sign`: add or replace the signature of a built package."""

import io
import os
import zipfile
from pathlib import Path

from epicstaff_plugin.cli.keys import read_secret_key
from epicstaff_plugin.cli.output import EXIT_INVALID, EXIT_OK, UsageError, print_problems
from epicstaff_plugin.package_layout import (
    CONTENTS_FILE_NAME,
    SIGNATURE_FILE_NAME,
    read_package_file,
)
from epicstaff_plugin.package_writer import ArchiveEntry, write_package
from epicstaff_plugin.problems import PackageProblemsError
from epicstaff_plugin.signing import sign_package


def sign(package_path: Path, key_path: Path) -> int:
    if not package_path.is_file():
        raise UsageError(f"{package_path} is not a file")
    secret_key = read_secret_key(key_path)
    try:
        package = read_package_file(package_path, ignore_signature=True)
    except PackageProblemsError as error:
        print_problems(error.problems)
        return EXIT_INVALID
    manifest = package.manifest
    signature = sign_package(package.contents, manifest.id, manifest.version, secret_key)
    # Written next to the package and moved over it only once the package is closed again:
    # Windows refuses to replace a file that is still open.
    signed = package_path.with_name(f".{package_path.name}.signed")
    try:
        with zipfile.ZipFile(package_path) as archive:
            entries = [_member_entry(archive, file.path) for file in package.files]
            entries.append(_bytes_entry(CONTENTS_FILE_NAME, package.contents))
            entries.append(_bytes_entry(SIGNATURE_FILE_NAME, signature.encode("utf-8")))
            write_package(signed, entries)
        os.replace(signed, package_path)
    finally:
        signed.unlink(missing_ok=True)
    print(f"signed {package_path} with key {secret_key.public_key.display_id}")
    return EXIT_OK


def _member_entry(archive: zipfile.ZipFile, path: str) -> ArchiveEntry:
    return ArchiveEntry(path, lambda: archive.open(path))


def _bytes_entry(path: str, data: bytes) -> ArchiveEntry:
    return ArchiveEntry(path, lambda: io.BytesIO(data))
