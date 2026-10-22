"""`epicstaff-plugin pack`: build a deterministic `.esplugin` package from a source directory."""

import io
import tempfile
from collections.abc import Sequence
from pathlib import Path

from epicstaff_plugin.cli.backend_wheels import (
    DEFAULT_PLATFORMS,
    linux_machine,
    packed_requirement_problems,
    read_local_wheel,
    with_backend_wheels,
)
from epicstaff_plugin.cli.keys import read_secret_key
from epicstaff_plugin.cli.output import EXIT_INVALID, EXIT_OK, UsageError, print_problems
from epicstaff_plugin.notices import OPEN_CODE_NOTICE
from epicstaff_plugin.package_layout import (
    CONTENTS_FILE_NAME,
    SIGNATURE_FILE_NAME,
    build_contents,
    read_package_file,
)
from epicstaff_plugin.package_source import PackageSource, collect_source
from epicstaff_plugin.package_writer import ArchiveEntry, write_package
from epicstaff_plugin.problems import MANIFEST_LOC, PackageProblemsError, Problem
from epicstaff_plugin.signing import SecretKey, sign_package


def pack(
    source_directory: Path,
    spa_directory: Path | None,
    key_path: Path | None,
    output: Path,
    *,
    download_wheels: bool = False,
    platforms: Sequence[str] = (),
    local_wheel_paths: Sequence[Path] = (),
) -> int:
    if not source_directory.is_dir():
        raise UsageError(f"{source_directory} is not a directory")
    if platforms and not download_wheels:
        raise UsageError("--platform applies only with --download-wheels")
    target_platforms = tuple(platforms) or DEFAULT_PLATFORMS
    for platform in target_platforms:
        linux_machine(platform)
    local_wheels = [read_local_wheel(path) for path in local_wheel_paths]
    secret_key = read_secret_key(key_path) if key_path is not None else None
    print(OPEN_CODE_NOTICE)
    # Downloaded wheels and the packaged lock live here until the package is written.
    with tempfile.TemporaryDirectory(prefix="epicstaff-plugin-pack-") as work_directory:
        try:
            source = collect_source(source_directory, spa_directory)
            if source.manifest.spa is not None and not source.includes_spa:
                raise PackageProblemsError(
                    [
                        Problem(
                            f"{MANIFEST_LOC}.spa", "pass the built single-page app with --spa-dir"
                        )
                    ]
                )
            if download_wheels or local_wheels:
                source = with_backend_wheels(
                    source,
                    Path(work_directory),
                    download=download_wheels,
                    platforms=target_platforms,
                    local_wheels=local_wheels,
                )
            if problems := packed_requirement_problems(source, target_platforms):
                raise PackageProblemsError(problems)
        except PackageProblemsError as error:
            print_problems(error.problems)
            return EXIT_INVALID
        return _write(source, secret_key, output)


def _write(source: PackageSource, secret_key: SecretKey | None, output: Path) -> int:
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
