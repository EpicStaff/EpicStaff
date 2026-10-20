"""A plugin's source directory: the files `pack` puts in a package, and their checks."""

import hashlib
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from epicstaff_plugin.contracts.manifest import MANIFEST_FILE_NAME, PluginManifest, parse_manifest
from epicstaff_plugin.package_layout import (
    MAX_ICON_BYTES,
    SPA_DIRECTORY,
    PackageFile,
    layout_problems,
    path_set_problems,
    size_problems,
)
from epicstaff_plugin.problems import MANIFEST_LOC, PackageProblemsError, Problem, archive_file_loc

# Copied from the source directory as found; only this editor and interpreter litter is left out.
IGNORED_FILE_NAMES = frozenset({".DS_Store"})
IGNORED_DIRECTORY_NAMES = frozenset({"__pycache__"})
SOURCE_DIRECTORIES = ("backend", "database")
_HASH_CHUNK_BYTES = 1024 * 1024


@dataclass(frozen=True)
class SourceFile:
    """A file on disk and the path it gets inside the package."""

    path: str
    source: Path


@dataclass(frozen=True)
class PackageSource:
    """Everything `pack` would put in a package, apart from `CONTENTS.json` and its signature."""

    manifest: PluginManifest
    files: tuple[SourceFile, ...]
    includes_spa: bool

    def describe(self) -> dict[str, PackageFile]:
        """Hash every file and return its `CONTENTS.json` entry, keyed by package path."""
        return {file.path: _describe(file) for file in self.files}

    def problems(self, described: dict[str, PackageFile]) -> list[Problem]:
        """Check the package these files would make against every layout rule and cap."""
        icon_file = next((file for file in self.files if file.path == self.manifest.icon), None)
        icon = _read_capped(icon_file.source, MAX_ICON_BYTES) if icon_file else None
        return [
            *path_set_problems(described),
            *size_problems(described.values()),
            *layout_problems(self.manifest, described, icon, check_spa=self.includes_spa),
        ]


def collect_source(source_directory: Path, spa_directory: Path | None) -> PackageSource:
    """Gather a plugin's package files from its source directory.

    Takes `manifest.json` and the icon it names from `source_directory`, `backend/` and
    `database/` as found there, and the built single-page app from `spa_directory` (placed
    under `spa/`).

    Raises:
        PackageProblemsError: The manifest is missing or invalid, or a file cannot be packed
            (a symbolic link, or not a regular file).
    """
    manifest_path = source_directory / MANIFEST_FILE_NAME
    if not manifest_path.is_file():
        raise PackageProblemsError([Problem(MANIFEST_LOC, f"{manifest_path} does not exist")])
    manifest = parse_manifest(manifest_path.read_bytes())

    problems: list[Problem] = []
    files = [SourceFile(MANIFEST_FILE_NAME, manifest_path)]
    icon_path = source_directory / manifest.icon
    if icon_path.is_file() and not icon_path.is_symlink():
        files.append(SourceFile(manifest.icon, icon_path))
    if spa_directory is not None:
        if manifest.spa is None:
            problems.append(
                Problem(f"{MANIFEST_LOC}.spa", "is missing, but an SPA directory was given")
            )
        elif not spa_directory.is_dir():
            problems.append(Problem(f"{MANIFEST_LOC}.spa", f"{spa_directory} is not a directory"))
        else:
            files.extend(_walk(spa_directory, SPA_DIRECTORY, problems.append))
    for name in SOURCE_DIRECTORIES:
        directory = source_directory / name
        if directory.is_dir():
            files.extend(_walk(directory, f"{name}/", problems.append))
    if problems:
        raise PackageProblemsError(problems)
    return PackageSource(
        manifest=manifest,
        files=tuple(sorted(files, key=lambda file: file.path)),
        includes_spa=spa_directory is not None,
    )


def _walk(directory: Path, prefix: str, report: Callable[[Problem], None]) -> list[SourceFile]:
    files = []
    for root, directory_names, file_names in os.walk(directory, followlinks=False):
        root_path = Path(root)
        directory_names[:] = sorted(
            name for name in directory_names if name not in IGNORED_DIRECTORY_NAMES
        )
        for name in directory_names:
            if (root_path / name).is_symlink():
                report(
                    Problem(
                        archive_file_loc(_package_path(root_path / name, directory, prefix)),
                        "is a symbolic link",
                    )
                )
        for name in sorted(file_names):
            if name in IGNORED_FILE_NAMES:
                continue
            source = root_path / name
            package_path = _package_path(source, directory, prefix)
            if source.is_symlink():
                report(Problem(archive_file_loc(package_path), "is a symbolic link"))
            elif not source.is_file():
                report(Problem(archive_file_loc(package_path), "is not a regular file"))
            else:
                files.append(SourceFile(package_path, source))
    return files


def _package_path(source: Path, directory: Path, prefix: str) -> str:
    return prefix + source.relative_to(directory).as_posix()


def _describe(file: SourceFile) -> PackageFile:
    digest = hashlib.sha256()
    size = 0
    with file.source.open("rb") as stream:
        while chunk := stream.read(_HASH_CHUNK_BYTES):
            digest.update(chunk)
            size += len(chunk)
    return PackageFile(path=file.path, size=size, sha256=digest.hexdigest())


def _read_capped(path: Path, limit: int) -> bytes:
    with path.open("rb") as stream:
        return stream.read(limit + 1)
