"""`epicstaff-plugin pack`: build a deterministic `.esplugin` package from a source directory."""

import io
from pathlib import Path

from epicstaff_plugin.cli.keys import read_secret_key
from epicstaff_plugin.cli.output import EXIT_INVALID, EXIT_OK, UsageError, print_problems
from epicstaff_plugin.notices import OPEN_CODE_NOTICE
from epicstaff_plugin.package_layout import (
    CONTENTS_FILE_NAME,
    SIGNATURE_FILE_NAME,
    build_contents,
    read_package_file,
)
from epicstaff_plugin.package_source import collect_source
from epicstaff_plugin.package_writer import ArchiveEntry, write_package
from epicstaff_plugin.problems import MANIFEST_LOC, PackageProblemsError, Problem
from epicstaff_plugin.signing import sign_package


def pack(
    source_directory: Path, spa_directory: Path | None, key_path: Path | None, output: Path
) -> int:
    if not source_directory.is_dir():
        raise UsageError(f"{source_directory} is not a directory")
    secret_key = read_secret_key(key_path) if key_path is not None else None
    print(OPEN_CODE_NOTICE)
    try:
        source = collect_source(source_directory, spa_directory)
    except PackageProblemsError as error:
        print_problems(error.problems)
        return EXIT_INVALID
    if source.manifest.spa is not None and not source.includes_spa:
        print_problems(
            [Problem(f"{MANIFEST_LOC}.spa", "pass the built single-page app with --spa-dir")]
        )
        return EXIT_INVALID
    described = source.describe()
    if problems := source.problems(described):
        print_problems(problems)
        return EXIT_INVALID

    manifest = source.manifest
    contents = build_contents(manifest.id, manifest.version, described.values())
    entries = [_file_entry(file.path, file.source) for file in source.files]
    entries.append(_bytes_entry(CONTENTS_FILE_NAME, contents))
    if secret_key is not None:
        signature = sign_package(contents, manifest.id, manifest.version, secret_key)
        entries.append(_bytes_entry(SIGNATURE_FILE_NAME, signature.encode("utf-8")))
    write_package(output, entries)

    # Read back with the same rules EpicStaff applies, so a file that changed while packing,
    # or one that compresses too well, is caught here rather than at upload.
    try:
        read_package_file(output)
    except PackageProblemsError as error:
        output.unlink(missing_ok=True)
        print_problems(error.problems)
        return EXIT_INVALID
    signed = f"signed with key {secret_key.public_key.display_id}" if secret_key else "unsigned"
    print(f"packed {output} ({manifest.id} {manifest.version}, {len(described)} files, {signed})")
    return EXIT_OK


def _bytes_entry(path: str, data: bytes) -> ArchiveEntry:
    return ArchiveEntry(path, lambda: io.BytesIO(data))


def _file_entry(path: str, source: Path) -> ArchiveEntry:
    return ArchiveEntry(path, lambda: source.open("rb"))
