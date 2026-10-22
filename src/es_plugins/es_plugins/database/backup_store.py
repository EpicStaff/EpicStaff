"""The backups the node holds: `backups/<id>/`, the agent's alone (see `es_plugins.layout`).

A backup is two files, the dump `<stem>.dump` and its metadata `<stem>.json`, where the dump's name
follows `BACKUP_FILE_NAME_PATTERN`. Both are written under a temporary name starting with `.`,
synced, and only then given their final names, the dump first. So a backup is complete exactly
when both final names are there, and only complete backups are listed:

- **Inventory.** Every complete backup of a plugin, newest first, at most
  `MAX_BACKUPS_PER_PLACEMENT`. It is read again only when the directory changed.
- **Deletion.** Only the names EpicStaff lists, the dump and its metadata both. A link is
  deleted, never followed.
- **Clean-up at agent start.** Temporary files, dumps without metadata, metadata without a dump
  and metadata the node cannot read are deleted: none of them is a backup.

Files are 0600 and the directories 0700, the agent's. Log line: `plugins.backup.deleted`.
"""

import contextlib
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal

from loguru import logger
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, ValidationError
from src.shared.models.plugin_nodes import (
    BACKUP_FILE_NAME_PATTERN,
    MAX_APPLIED_MIGRATIONS,
    MAX_BACKUPS_PER_PLACEMENT,
    BackupFileReport,
    BackupReason,
    InstallationId,
    LedgerEntry,
    PackageVersion,
    PositiveInt,
    Sha256Hex,
)

from es_plugins.database.database_settings import (
    MAX_DATABASE_SETTINGS,
    MAX_SETTING_LENGTH,
    MAX_SETTING_NAME_LENGTH,
    DatabaseSetting,
)
from es_plugins.layout import NodeLayout, check_plugin_identifier

METADATA_FORMAT = 1
DUMP_SUFFIX = ".dump"
METADATA_SUFFIX = ".json"
TEMPORARY_PREFIX = "."
MAX_METADATA_BYTES = 1024 * 1024
_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_DUMP_NAME = re.compile(BACKUP_FILE_NAME_PATTERN)


class _Metadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SettingEntry(_Metadata):
    name: Annotated[str, StringConstraints(max_length=MAX_SETTING_NAME_LENGTH)]
    value: Annotated[str, StringConstraints(max_length=MAX_SETTING_LENGTH)]


class BackupMetadata(_Metadata):
    """What the node knows of a backup, kept next to its dump. The node's own format."""

    format: Literal[1]
    plugin: Annotated[str, StringConstraints(max_length=32)]
    installation_id: InstallationId
    database_name: Annotated[str, StringConstraints(max_length=63)]
    upgrade_id: PositiveInt
    reason: BackupReason
    version: PackageVersion
    """The plugin version whose migrations the database held."""

    restore_id: PositiveInt | None = None
    """For a `pre_restore` backup: the restore it was taken before, so a restore that is run
    again after an agent restart reuses it instead of backing up a half-restored database."""

    created_at: AwareDatetime
    size_bytes: PositiveInt
    sha256: Sha256Hex
    pg_dump_version: Annotated[str, StringConstraints(max_length=200)]
    server_version: Annotated[str, StringConstraints(max_length=200)]
    database_settings: Annotated[list[SettingEntry], Field(max_length=MAX_DATABASE_SETTINGS)]
    """The database's own settings, which a dump does not hold; a restore sets them again."""

    ledger: Annotated[list[LedgerEntry], Field(max_length=MAX_APPLIED_MIGRATIONS)] | None
    """The migration ledger as the dump holds it; None when the dump's ledger could not be read."""

    def settings(self) -> tuple[DatabaseSetting, ...]:
        return tuple(
            DatabaseSetting(name=entry.name, value=entry.value) for entry in self.database_settings
        )


@dataclass(frozen=True)
class StoredBackup:
    """A complete backup: its dump's name and path, and its metadata."""

    file_name: str
    path: Path
    metadata: BackupMetadata

    def report(self) -> BackupFileReport:
        """Raises: ValidationError: the metadata does not fit the report (e.g. another name)."""
        metadata = self.metadata
        return BackupFileReport(
            file_name=self.file_name,
            installation_id=metadata.installation_id,
            upgrade_id=metadata.upgrade_id,
            reason=metadata.reason,
            version=metadata.version,
            size_bytes=metadata.size_bytes,
            sha256=metadata.sha256,
            created_at=metadata.created_at,
        )


def metadata_name(dump_name: str) -> str:
    return dump_name.removesuffix(DUMP_SUFFIX) + METADATA_SUFFIX


def temporary_name(final_name: str) -> str:
    return TEMPORARY_PREFIX + final_name + ".partial"


class BackupStore:
    def __init__(self, layout: NodeLayout):
        self._layout = layout
        # plugin -> (the directory's mtime and inode, its complete backups).
        self._inventories: dict[str, tuple[tuple[int, int], tuple[StoredBackup, ...]]] = {}

    def directory(self, plugin: str) -> Path:
        """`backups/<plugin>/`, made 0700 if it is missing."""
        directory = self._layout.plugin_backups(plugin)
        with contextlib.suppress(FileExistsError):
            os.mkdir(directory, 0o700)
        info = os.lstat(directory)
        if not stat.S_ISDIR(info.st_mode):
            raise OSError(f"{directory} is not a directory")
        return directory

    def inventory(self, plugin: str) -> tuple[StoredBackup, ...]:
        """The plugin's complete backups, newest first, at most `MAX_BACKUPS_PER_PLACEMENT`."""
        directory = self._layout.plugin_backups(check_plugin_identifier(plugin))
        try:
            info = os.lstat(directory)
        except FileNotFoundError:
            self._inventories.pop(plugin, None)
            return ()
        if not stat.S_ISDIR(info.st_mode):
            return ()
        key = (info.st_mtime_ns, info.st_ino)
        cached = self._inventories.get(plugin)
        if cached is not None and cached[0] == key:
            return cached[1]
        backups = _complete_backups(directory)
        backups.sort(
            key=lambda backup: (backup.metadata.created_at, backup.file_name), reverse=True
        )
        listed = tuple(backups[:MAX_BACKUPS_PER_PLACEMENT])
        self._inventories[plugin] = (key, listed)
        return listed

    def find(self, plugin: str, file_name: str) -> StoredBackup | None:
        return next(
            (backup for backup in self.inventory(plugin) if backup.file_name == file_name), None
        )

    def delete(self, plugin: str, file_names: list[str]) -> list[str]:
        """Delete these backups, dump and metadata; return the names that were there.

        Names that are not backup names are ignored; a missing file is fine.
        """
        directory = self._layout.plugin_backups(check_plugin_identifier(plugin))
        deleted = []
        try:
            descriptor = os.open(directory, _DIRECTORY_FLAGS)
        except FileNotFoundError:
            return deleted
        try:
            for name in file_names:
                if not _DUMP_NAME.fullmatch(name):
                    continue
                removed = [_unlink(descriptor, entry) for entry in (name, metadata_name(name))]
                if any(removed):
                    deleted.append(name)
                    logger.info("plugins.backup.deleted plugin={} file={}", plugin, name)
        finally:
            os.close(descriptor)
        return deleted

    def clean_up(self) -> None:
        """At agent start: delete everything in the backups tree that is not a complete backup."""
        root = self._layout.backups_root
        try:
            plugins = os.listdir(root)
        except FileNotFoundError:
            return
        for plugin in plugins:
            directory = root / plugin
            if not stat.S_ISDIR(os.lstat(directory).st_mode):
                continue
            descriptor = os.open(directory, _DIRECTORY_FLAGS)
            try:
                names = set(os.listdir(descriptor))
                complete = {backup.file_name for backup in _complete_backups(directory)}
                keep = complete | {metadata_name(name) for name in complete}
                for name in names - keep:
                    _unlink(descriptor, name)
                    logger.info("plugins.backup.deleted plugin={} file={}", plugin, name)
            finally:
                os.close(descriptor)

    @staticmethod
    def create_temporary(directory: Path, final_name: str) -> tuple[Path, int]:
        """Create the temporary file a backup's dump or metadata is written to, 0600.

        Returns its path and a descriptor open for writing; a file of that name is refused.
        """
        path = directory / temporary_name(final_name)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
        return path, os.open(path, flags, 0o600)

    def write_metadata(
        self, directory: Path, final_dump_name: str, metadata: BackupMetadata
    ) -> Path:
        """Write the metadata under its temporary name, synced; return that path."""
        path, descriptor = self.create_temporary(directory, metadata_name(final_dump_name))
        try:
            content = memoryview(metadata.model_dump_json().encode())
            while content:
                content = content[os.write(descriptor, content) :]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return path

    def publish(self, directory: Path, dump: Path, metadata: Path, final_dump_name: str) -> Path:
        """Give a synced dump and metadata their final names, the dump first, and sync the directory.

        A final name already there is never replaced: `os.link` refuses it.

        Raises:
            FileExistsError: A backup of that name exists.
        """
        final_dump = directory / final_dump_name
        os.link(dump, final_dump)
        os.unlink(dump)
        try:
            os.link(metadata, directory / metadata_name(final_dump_name))
        except BaseException:
            # A dump without its metadata is not a backup.
            os.unlink(final_dump)
            raise
        os.unlink(metadata)
        descriptor = os.open(directory, _DIRECTORY_FLAGS)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return final_dump


def _complete_backups(directory: Path) -> list[StoredBackup]:
    try:
        names = set(os.listdir(directory))
    except FileNotFoundError:
        return []
    backups = []
    for name in names:
        match = _DUMP_NAME.fullmatch(name)
        if match is None or metadata_name(name) not in names:
            continue
        dump = directory / name
        metadata = _read_metadata(directory / metadata_name(name))
        if (
            metadata is None
            or (metadata.upgrade_id, metadata.reason) != (int(match.group(1)), match.group(2))
            or metadata.plugin != directory.name
            or not stat.S_ISREG(os.lstat(dump).st_mode)
        ):
            continue
        backups.append(StoredBackup(file_name=name, path=dump, metadata=metadata))
    return backups


def _read_metadata(path: Path) -> BackupMetadata | None:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError:
        return None
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            return None
        content = b""
        while len(content) <= MAX_METADATA_BYTES and (chunk := os.read(descriptor, 65536)):
            content += chunk
    finally:
        os.close(descriptor)
    if len(content) > MAX_METADATA_BYTES:
        return None
    try:
        return BackupMetadata.model_validate_json(content)
    except (ValidationError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def _unlink(directory_descriptor: int, name: str) -> bool:
    """Delete a file or link by name; a directory there is left alone (the agent makes none)."""
    try:
        if stat.S_ISDIR(os.lstat(name, dir_fd=directory_descriptor).st_mode):
            return False
        os.unlink(name, dir_fd=directory_descriptor)
    except FileNotFoundError:
        return False
    return True
