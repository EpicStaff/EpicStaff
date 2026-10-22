"""Back up a plugin's database with `pg_dump`, as `plugins_backup`.

`BackupService.backup` runs these steps; the caller holds the placement's database lock, shared
with provisioning and the limits watchdog:

1. **Room**, on an admin session to `postgres`: the database's template mark and connection
   limit are put back (`database_attributes`), its size, the server's version and the
   database's own settings are read. The node's free disk space minus its floor must be at least
   the database's size.
2. **Dump.** `pg_dump --format=custom` as `plugins_backup` on the plugin's database, with session
   options that override every setting the plugin stored for it (`BACKUP_SESSION_OPTIONS`). Its
   output is written to a temporary file in `backups/<id>/`, which is hashed as it is written.
   `pg_dump` reads catalogs and copies rows: with the backup role's BYPASSRLS and
   `row_security=off`, no policy, trigger, view or function of the plugin runs.
3. **Verify**: `pg_restore --list` reads the archive (`archive`), and the ledger is read from it.
   A `pre_upgrade` backup must hold the ledger's data: EpicStaff decides from the ledger whether
   an upgrade can be cancelled. A `pre_restore` backup need not: after a restore that failed, the
   database it backs up may hold nothing, and that state is the one a later restore undoes.
4. **Metadata** (`BackupMetadata`), synced like the dump, and both given their final names, the
   dump first, then the directory synced.

A failed dump, a failed verification or a crash before the metadata leaves nothing under a final
name; the temporary files go at once, or at the next agent start. Log lines:
`plugins.database.backed_up` and `plugins.database.backup_failed` (reason `disk`, `dump`, `verify`
or `unreachable`). Neither carries the password, which only `pg_dump`'s own environment holds.
"""

import asyncio
import contextlib
import hashlib
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from loguru import logger
from src.shared.models.plugin_nodes import (
    BackupReason,
    DesiredDatabase,
    backup_file_name,
)

from es_plugins.database.archive import check_archive, read_archive_ledger
from es_plugins.database.backup_store import (
    METADATA_FORMAT,
    BackupMetadata,
    BackupStore,
    SettingEntry,
    StoredBackup,
)
from es_plugins.database.connections import (
    BACKUP_ROLE,
    BACKUP_SESSION_OPTIONS,
    DatabaseConnector,
    DatabaseUnreachableError,
)
from es_plugins.database.database_attributes import reset_database_attributes
from es_plugins.database.database_settings import read_database_settings
from es_plugins.database.postgres_client import PostgresClient, PostgresToolError, ToolLogin
from es_plugins.database.provisioner import database_size
from es_plugins.node_disk import FLOOR_BYTES, NodeDisk

BACKUP_APPLICATION_NAME = "epicstaff-node-backup"
DUMP_ARGUMENTS = [
    "--format=custom",
    "--no-password",
    "--lock-wait-timeout=60000",
    "--no-publications",
    "--no-subscriptions",
    "--no-security-labels",
    "--no-tablespaces",
]
FailureReason = Literal["disk", "dump", "verify"]
_MIB = 1024 * 1024
# libpq's words for a server it could not reach or lost; an authentication refusal is not one.
_UNREACHABLE_MARKERS = (
    "could not connect",
    "server closed the connection unexpectedly",
    "no connection to the server",
    "Connection refused",
    "could not translate host name",
    "timeout expired",
    "Connection timed out",
)
_LARGE_OBJECT_REFUSAL = "permission denied for large object"


class BackupError(Exception):
    """A permanent failure of a backup: the same attempt would fail the same way."""

    def __init__(self, reason: FailureReason, message: str):
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class BackupRequest:
    plugin: str
    database: DesiredDatabase
    upgrade_id: int
    reason: BackupReason
    version: str
    """The plugin version whose migrations the database holds."""

    restore_id: int | None = None


class BackupService:
    def __init__(
        self,
        connector: DatabaseConnector,
        client: PostgresClient,
        store: BackupStore,
        disk: NodeDisk,
        backup_password: str,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        self._connector = connector
        self._client = client
        self._store = store
        self._disk = disk
        self._backup_password = backup_password
        self._clock = clock
        self._pg_dump_version: str | None = None

    async def backup(self, request: BackupRequest) -> StoredBackup:
        """Take a complete backup of the database; see the module.

        Raises:
            BackupError: There is not enough room, or the dump or its verification failed.
            DatabaseUnreachableError: plugins_db cannot be reached now (transient).
        """
        started = time.monotonic()
        try:
            stored = await self._backup(request)
        except BackupError as error:
            _log_failure(request.plugin, error.reason)
            raise
        except DatabaseUnreachableError:
            _log_failure(request.plugin, "unreachable")
            raise
        logger.info(
            "plugins.database.backed_up plugin={} file={} reason={} size_bytes={} duration_ms={}",
            request.plugin,
            stored.file_name,
            request.reason,
            stored.metadata.size_bytes,
            round((time.monotonic() - started) * 1000),
        )
        return stored

    async def _backup(self, request: BackupRequest) -> StoredBackup:
        desired = request.database
        async with self._connector.admin_session(desired.server) as admin:
            if await reset_database_attributes(admin, desired.database_name, desired.owner_role):
                logger.warning(
                    "plugins.database.attributes_reset plugin={} database={}",
                    request.plugin,
                    desired.database_name,
                )
            size = await database_size(admin, desired.database_name)
            cursor = await admin.execute("SHOW server_version")
            server_version = (await cursor.fetchone())[0]
            settings = await read_database_settings(admin, desired.database_name)
        if settings.skipped:
            logger.warning(
                "plugins.database.settings_skipped plugin={} count={}",
                request.plugin,
                settings.skipped,
            )
        free = self._disk.free().bytes
        if free - FLOOR_BYTES < size:
            raise BackupError(
                "disk",
                f"not enough disk space for the database backup: about {-(-size // _MIB)} MB "
                f"needed, {max(free - FLOOR_BYTES, 0) // _MIB} MB free",
            )
        if self._pg_dump_version is None:
            try:
                self._pg_dump_version = await self._client.version("pg_dump")
            except PostgresToolError as error:
                raise BackupError("dump", f"pg_dump cannot run: {error}") from None

        directory = await asyncio.to_thread(self._store.directory, request.plugin)
        created_at = self._clock().replace(microsecond=0)
        # One name per second: a name already there is never replaced.
        while (
            directory / backup_file_name(created_at, request.upgrade_id, request.reason)
        ).exists():
            created_at += timedelta(seconds=1)
        final_name = backup_file_name(created_at, request.upgrade_id, request.reason)
        dump_path, descriptor = self._store.create_temporary(directory, final_name)
        metadata_path = None
        try:
            try:
                size, sha256 = await self._dump(desired, descriptor)
                await asyncio.to_thread(os.fsync, descriptor)
            finally:
                os.close(descriptor)
            if size == 0:
                raise BackupError("dump", "pg_dump wrote nothing")
            await self._verify(dump_path, ledger_required=request.reason == "pre_upgrade")
            ledger = await self._read_ledger(dump_path)
            metadata = BackupMetadata(
                format=METADATA_FORMAT,
                plugin=request.plugin,
                installation_id=desired.installation_id,
                database_name=desired.database_name,
                upgrade_id=request.upgrade_id,
                reason=request.reason,
                version=request.version,
                restore_id=request.restore_id,
                created_at=created_at,
                size_bytes=size,
                sha256=sha256,
                pg_dump_version=self._pg_dump_version[:200],
                server_version=str(server_version)[:200],
                database_settings=[
                    SettingEntry(name=setting.name, value=setting.value)
                    for setting in settings.settings
                ],
                ledger=list(ledger) if ledger is not None else None,
            )
            metadata_path = await asyncio.to_thread(
                self._store.write_metadata, directory, final_name, metadata
            )
            final = await asyncio.to_thread(
                self._store.publish, directory, dump_path, metadata_path, final_name
            )
        except BaseException:
            for leftover in (dump_path, metadata_path):
                if leftover is not None:
                    with contextlib.suppress(FileNotFoundError):
                        os.unlink(leftover)
            raise
        return StoredBackup(file_name=final_name, path=final, metadata=metadata)

    async def _dump(self, desired: DesiredDatabase, descriptor: int) -> tuple[int, str]:
        """Write the dump to `descriptor`; return its size and sha256."""
        login = ToolLogin(
            server=desired.server,
            database=desired.database_name,
            user=BACKUP_ROLE,
            password=self._backup_password,
            options=BACKUP_SESSION_OPTIONS,
            application_name=BACKUP_APPLICATION_NAME,
        )

        digest = hashlib.sha256()
        size = 0

        async def write(chunk: bytes) -> bool:
            nonlocal size
            await asyncio.to_thread(_write_all, descriptor, chunk)
            digest.update(chunk)
            size += len(chunk)
            return True

        try:
            await self._client.run("pg_dump", DUMP_ARGUMENTS, login=login, stdout=write)
        except PostgresToolError as error:
            text = str(error)
            if any(marker in text for marker in _UNREACHABLE_MARKERS):
                raise DatabaseUnreachableError(
                    f"the backup could not reach plugins_db: {text}"
                ) from None
            if _LARGE_OBJECT_REFUSAL in text:
                raise BackupError(
                    "dump",
                    "the database holds large objects, which backups cannot read: store binary "
                    f"data in bytea columns instead ({text})",
                ) from None
            raise BackupError("dump", text) from None
        return size, digest.hexdigest()

    async def _verify(self, dump_path, *, ledger_required: bool) -> None:
        try:
            listed = await check_archive(self._client, dump_path)
        except PostgresToolError as error:
            raise BackupError("verify", f"the dump cannot be read back: {error}") from None
        if ledger_required and not listed:
            raise BackupError("verify", "the dump holds no data of the migration ledger")

    async def _read_ledger(self, dump_path):
        try:
            return await read_archive_ledger(self._client, dump_path)
        except PostgresToolError as error:
            raise BackupError("verify", f"the dump's ledger cannot be read: {error}") from None


def _write_all(descriptor: int, chunk: bytes) -> None:
    view = memoryview(chunk)
    while view:
        view = view[os.write(descriptor, view) :]


def _log_failure(plugin: str, reason: str) -> None:
    logger.error("plugins.database.backup_failed plugin={} reason={}", plugin, reason)
