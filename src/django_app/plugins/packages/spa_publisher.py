import os
import re
import shutil
import tempfile
import zipfile
from collections.abc import Iterable
from pathlib import Path

from django.conf import settings
from epicstaff_plugin.contracts.manifest import IDENTIFIER_PATTERN, SEMVER_PATTERN
from epicstaff_plugin.package_layout import SPA_DIRECTORY
from epicstaff_plugin.paths import path_problem

CURRENT_LINK = "current"
# nginx answers the plugin's SPA paths with the platform's maintenance page while this empty
# file exists in the plugin's directory. Version directories start with a digit, so the name
# never collides with one, nor with `current`.
MAINTENANCE_FLAG = "maintenance"
DIRECTORY_MODE = 0o755
FILE_MODE = 0o644
_COPY_CHUNK_BYTES = 1024 * 1024


class UnsafeSpaPathError(ValueError):
    """A path that would land outside the plugin's SPA directory, or an unsafe name."""


class SpaPublisher:
    """Writes plugins' single-page apps to the `plugin_spa` volume nginx serves read-only.

    Layout: `<root>/<identifier>/<version>/` holds a package's `spa/` tree, and
    `<root>/<identifier>/current` is a relative symlink to the version nginx serves. Publishing
    is two steps so a caller can make the second one wait for its transaction to commit:
    `write_version` writes the files (in a hidden staging directory, renamed into place), and
    `switch_current` repoints `current` with one `os.replace`. nginx therefore never serves a
    half-written or unapproved version. Directories get mode 0755 and files 0644, readable by
    nginx's worker user. While the plugin is upgraded, `set_maintenance` puts the maintenance
    flag in its directory.
    """

    def __init__(self, root: Path | None = None):
        self._root = root or settings.PLUGINS_SPA_ROOT

    def write_version(
        self, identifier: str, version: str, archive: zipfile.ZipFile, spa_paths: Iterable[str]
    ) -> Path:
        """Write the archive members `spa_paths` (all under `spa/`) as one version's files.

        Nothing is served from them until `switch_current` names the version.

        Raises:
            UnsafeSpaPathError: The identifier, version or a member path is unsafe; nothing
                is written.
        """
        plugin_directory = self._plugin_directory(identifier)
        version_directory = self._version_directory(identifier, version)
        plugin_directory.mkdir(exist_ok=True)
        os.chmod(plugin_directory, DIRECTORY_MODE)
        staging = Path(tempfile.mkdtemp(prefix=f".{version}.", dir=plugin_directory))
        try:
            for archive_path in spa_paths:
                self._write_member(archive, archive_path, staging)
            for directory, _, _ in os.walk(staging):
                os.chmod(directory, DIRECTORY_MODE)
            if version_directory.exists():
                # Left by an approval of this version that did not commit.
                shutil.rmtree(version_directory)
            os.rename(staging, version_directory)
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        return version_directory

    def switch_current(self, identifier: str, version: str) -> None:
        """Serve `version` from now on; it must have been written with `write_version`."""
        plugin_directory = self._plugin_directory(identifier)
        if not self._version_directory(identifier, version).is_dir():
            raise FileNotFoundError(f"version {version} of {identifier} was never written")
        temporary = plugin_directory / f"{CURRENT_LINK}.tmp"
        temporary.unlink(missing_ok=True)
        os.symlink(version, temporary)
        os.replace(temporary, plugin_directory / CURRENT_LINK)

    def discard_version(self, identifier: str, version: str) -> None:
        """Remove a written version that never became current; the current one is kept."""
        version_directory = self._version_directory(identifier, version)
        current = self._plugin_directory(identifier) / CURRENT_LINK
        if current.is_symlink() and os.readlink(current) == version:
            return
        shutil.rmtree(version_directory, ignore_errors=True)

    def remove_plugin(self, identifier: str) -> None:
        """Remove every file of a plugin, so its host serves nothing any more."""
        shutil.rmtree(self._plugin_directory(identifier), ignore_errors=True)

    def has_version(self, identifier: str, version: str) -> bool:
        """Whether `version`'s files were written."""
        return self._version_directory(identifier, version).is_dir()

    def current_version(self, identifier: str) -> str | None:
        """The version `current` names, or None when there is no link."""
        current = self._plugin_directory(identifier) / CURRENT_LINK
        return os.readlink(current) if current.is_symlink() else None

    def remove_current(self, identifier: str) -> None:
        """Serve no version any more, for a plugin whose new version has no SPA."""
        (self._plugin_directory(identifier) / CURRENT_LINK).unlink(missing_ok=True)

    def prune_versions(self, identifier: str, keep: set[str]) -> None:
        """Remove every version directory of the plugin except those in `keep`.

        Only directories named like a version are touched; `current`, the maintenance flag,
        and staging directories of an approval in progress are left. Links are never followed.
        """
        plugin_directory = self._plugin_directory(identifier)
        if not plugin_directory.is_dir():
            return
        for entry in plugin_directory.iterdir():
            if (
                entry.name in keep
                or entry.is_symlink()
                or not entry.is_dir()
                or not re.fullmatch(SEMVER_PATTERN, entry.name)
            ):
                continue
            shutil.rmtree(entry, ignore_errors=True)

    def maintenance_flag_set(self, identifier: str) -> bool:
        return (self._plugin_directory(identifier) / MAINTENANCE_FLAG).is_file()

    def set_maintenance(self, identifier: str, on: bool) -> None:
        """Put the maintenance flag in the plugin's directory, or take it away.

        On: the directory is created (0755) when the plugin has no SPA files yet, and the flag
        is written as a temporary file and moved into place with `os.replace`, mode 0644, so
        nginx sees either no flag or the whole one. Off: the flag is removed; a missing one is
        fine.
        """
        plugin_directory = self._plugin_directory(identifier)
        flag = plugin_directory / MAINTENANCE_FLAG
        if not on:
            flag.unlink(missing_ok=True)
            return
        plugin_directory.mkdir(exist_ok=True)
        os.chmod(plugin_directory, DIRECTORY_MODE)
        descriptor, temporary = tempfile.mkstemp(
            prefix=f".{MAINTENANCE_FLAG}.", dir=plugin_directory
        )
        try:
            os.close(descriptor)
            os.chmod(temporary, FILE_MODE)
            os.replace(temporary, flag)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise

    def _plugin_directory(self, identifier: str) -> Path:
        _require_match(IDENTIFIER_PATTERN, identifier, "plugin identifier")
        return self._root / identifier

    def _version_directory(self, identifier: str, version: str) -> Path:
        _require_match(SEMVER_PATTERN, version, "version")
        return self._plugin_directory(identifier) / version

    @staticmethod
    def _write_member(archive: zipfile.ZipFile, archive_path: str, staging: Path) -> None:
        relative = archive_path.removeprefix(SPA_DIRECTORY)
        if relative == archive_path or path_problem(relative):
            raise UnsafeSpaPathError(f"{archive_path!r} is not a safe path under {SPA_DIRECTORY}")
        target = staging.joinpath(*relative.split("/"))
        if not target.resolve().is_relative_to(staging.resolve()):
            raise UnsafeSpaPathError(f"{archive_path!r} leaves the SPA directory")
        target.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(archive_path) as source, target.open("xb") as destination:
            shutil.copyfileobj(source, destination, _COPY_CHUNK_BYTES)
        os.chmod(target, FILE_MODE)


def _require_match(pattern: str, value: str, what: str) -> None:
    if not re.fullmatch(pattern, value):
        raise UnsafeSpaPathError(f"{value!r} is not a valid {what}")
