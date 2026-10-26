"""A plugin's source directory: the files `pack` puts in a package, and their checks."""

import hashlib
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from epicstaff_plugin.contracts.manifest import MANIFEST_FILE_NAME, PluginManifest, parse_manifest
from epicstaff_plugin.package_layout import (
    BACKEND_REQUIREMENTS,
    MAX_ICON_BYTES,
    MAX_NAVIGATION_ICON_BYTES,
    SECRET_SCAN_BYTES,
    SPA_DIRECTORY,
    PackageFile,
    is_scanned_for_secrets,
    layout_problems,
    path_set_problems,
    secret_problem,
    size_problems,
)
from epicstaff_plugin.problems import MANIFEST_LOC, PackageProblemsError, Problem, archive_file_loc
from epicstaff_plugin.requirements_lock import MAX_REQUIREMENTS_LOCK_BYTES

# Copied from the source directory as found; only this editor and interpreter litter is left out.
IGNORED_FILE_NAMES = frozenset({".DS_Store"})
IGNORED_DIRECTORY_NAMES = frozenset({"__pycache__"})
# Inputs that stay in the source: the lock is compiled from requirements.in, and only the
# lock is installed.
SOURCE_ONLY_PATHS = frozenset({"backend/requirements.in"})
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

    def problems(
        self, described: dict[str, PackageFile], *, require_sdk_pin: bool = True
    ) -> list[Problem]:
        """Check the package these files would make against every layout rule and cap.

        `require_sdk_pin=False` accepts a lock that does not pin `epicstaff-plugin` yet.
        """
        return [
            *path_set_problems(described),
            *size_problems(described.values()),
            *layout_problems(
                self.manifest,
                described,
                self._read(self.manifest.icon, MAX_ICON_BYTES),
                navigation_icons={
                    path: data
                    for path in self.manifest.navigation_icon_paths
                    if (data := self._read(path, MAX_NAVIGATION_ICON_BYTES)) is not None
                },
                requirements_lock=self._read(BACKEND_REQUIREMENTS, MAX_REQUIREMENTS_LOCK_BYTES),
                check_spa=self.includes_spa,
                require_sdk_pin=require_sdk_pin,
            ),
            *self.secret_problems(),
        ]

    def secret_problems(self) -> list[Problem]:
        """Name every file that holds an EpicStaff key or runtime file (`secret_problem`)."""
        problems = []
        for file in self.files:
            if not is_scanned_for_secrets(file.path):
                continue
            head = _read_capped(file.source, SECRET_SCAN_BYTES)
            complete = len(head) <= SECRET_SCAN_BYTES
            if problem := secret_problem(file.path, head[:SECRET_SCAN_BYTES], complete=complete):
                problems.append(problem)
        return problems

    def file(self, path: str) -> SourceFile | None:
        return next((file for file in self.files if file.path == path), None)

    def _read(self, path: str, limit: int) -> bytes | None:
        file = self.file(path)
        return _read_capped(file.source, limit) if file else None


def collect_source(source_directory: Path, spa_directory: Path | None) -> PackageSource:
    """Gather a plugin's package files from its source directory.

    Takes `manifest.json`, the icon it names and the menu icons `spa.navigation` names (other
    files under `icons/` stay behind) from `source_directory`, `backend/` and `database/` as
    found there, and the built single-page app from `spa_directory` (placed under `spa/`).
    Nothing is taken from outside `source_directory` through a symbolic link: a `backend/` or
    `database/` folder that leads outside is refused, and a named icon that is missing, not a
    regular file, or reached through a link to outside is left out, which the layout check
    reports as missing.

    Raises:
        PackageProblemsError: The manifest is missing or invalid, or a file cannot be packed
            (a symbolic link, or not a regular file).
    """
    manifest_path = source_directory / MANIFEST_FILE_NAME
    if not manifest_path.is_file():
        raise PackageProblemsError([Problem(MANIFEST_LOC, f"{manifest_path} does not exist")])
    manifest = parse_manifest(manifest_path.read_bytes())

    source_root = source_directory.resolve()
    problems: list[Problem] = []
    files = [SourceFile(MANIFEST_FILE_NAME, manifest_path)]
    for icon in (manifest.icon, *manifest.navigation_icon_paths):
        icon_path = source_directory / icon
        if (
            icon_path.is_file()
            and not icon_path.is_symlink()
            and _is_inside(icon_path, source_root)
        ):
            files.append(SourceFile(icon, icon_path))
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
        if not directory.is_dir():
            continue
        # The walk follows no link below `directory`, so every file it takes is inside the
        # source once `directory` itself is.
        if _is_inside(directory, source_root):
            files.extend(_walk(directory, f"{name}/", problems.append))
        else:
            problems.append(Problem(archive_file_loc(name), "is a symbolic link"))
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
            elif package_path not in SOURCE_ONLY_PATHS:
                files.append(SourceFile(package_path, source))
    return files


def _is_inside(path: Path, source_root: Path) -> bool:
    return path.resolve().is_relative_to(source_root)


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
