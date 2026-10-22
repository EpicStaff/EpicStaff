"""Replace a plugin's database with one of its backups, during a failed upgrade.

`RestoreService.restore` runs these steps. The caller holds the placement's database lock and has
stopped the plugin's process; `on_step` is told when each begins, for the node's report.

1. **verify**: the backup is complete, its sha256 is the one EpicStaff names (the file is hashed
   again), its metadata names this installation and database, and `pg_restore --list` reads it.
   Otherwise nothing is changed. A backup of an empty database (taken before a restore that then
   failed) is a backup like any other: restoring it gives that state back.
2. **backup**: a `pre_restore` backup of the database as it is (`BackupService`), the way back.
   If a restore of this id took one already (the agent restarted), that one is used. If it fails,
   nothing is changed.
3. **close**: the database is still this installation's (`installation_lookup`); the app role
   cannot log in any more, and every session of the app role and the owner is ended, through
   `plugins_admin`'s `pg_signal_backend`. A session that survives is a failure.
4. **recreate**, from `postgres`: the database's template mark and connection limit are put back
   (`database_attributes`), it is dropped as its owner (a plain `DROP`, which a session still
   connected makes PostgreSQL refuse: tried again later), created again owned by the owner, from
   `template0`, and only the five roles may connect to it (`provisioner.grant_connect`).
5. **restore**: the owner may log in for this run only (a one-time password, one connection, ten
   minutes), and `pg_restore` runs **with the owner as the session user**, in one transaction,
   with row security on, and with session options that override every setting the plugin stored
   for its owner role (`RESTORE_SESSION_OPTIONS`). The plugin's SQL in the dump (functions run by
   checks, indexes, materialized views) runs as the owner, and no `RESET ROLE` can lead anywhere
   else. Never `--role`, never as `plugins_admin` or `postgres`. Whatever happens, the owner goes
   back to NOLOGIN without a password, and its sessions are ended.
6. **settings**: the database's own settings, from the backup's metadata, are set again
   (`database_settings`).
7. **assert**: `DatabaseProvisioner.ensure` without migrations: the roles, the app role able to
   log in with its password, CONNECT, the limits, and every check of provisioning. It reads the
   restored ledger.

A failure in step 4 or later leaves the database empty or as it was before step 5 (the restore is
one transaction): the pre-restore backup is the way back. Log lines: `plugins.database.restored`
and `plugins.database.restore_failed`.
"""

import asyncio
import hashlib
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

import psycopg
from loguru import logger
from psycopg import errors, sql
from src.shared.models.plugin_nodes import DesiredDatabase, DesiredRestore, RestoreStep

from es_plugins.database.archive import check_archive
from es_plugins.database.backup_service import BackupError, BackupRequest, BackupService
from es_plugins.database.backup_store import BackupStore, StoredBackup
from es_plugins.database.connections import (
    RESTORE_SESSION_OPTIONS,
    DatabaseConnector,
    DatabaseProvisioningError,
    DatabaseUnreachableError,
    describe_error,
    end_sessions,
)
from es_plugins.database.database_attributes import reset_database_attributes
from es_plugins.database.database_settings import apply_database_settings
from es_plugins.database.installation_lookup import find_installation
from es_plugins.database.migration_runner import (
    OWNER_LOGIN_WINDOW,
    close_owner_login,
    open_owner_login,
)
from es_plugins.database.postgres_client import PostgresClient, PostgresToolError, ToolLogin
from es_plugins.database.provisioner import DatabaseProvisioner, ProvisionedDatabase, grant_connect

RESTORE_APPLICATION_NAME = "epicstaff-node-restore"
SESSIONS_END_SECONDS = 10.0
RESTORE_ARGUMENTS = [
    "--no-password",
    "--single-transaction",
    "--exit-on-error",
    "--no-owner",
    "--no-tablespaces",
    "--no-publications",
    "--no-subscriptions",
    "--no-security-labels",
    # With row security off, a materialized view over a table with FORCE ROW LEVEL SECURITY cannot
    # be refreshed by its owner; on, it is refreshed under the plugin's own policies.
    "--enable-row-security",
]
_HASH_CHUNK_BYTES = 1024 * 1024


class RestoreError(Exception):
    """The restore failed at `step`; `temporary` when trying again later may succeed."""

    def __init__(self, step: RestoreStep, message: str, *, temporary: bool = False):
        super().__init__(message)
        self.step = step
        self.temporary = temporary


@dataclass(frozen=True)
class RestoreOutcome:
    pre_restore: StoredBackup
    provisioned: ProvisionedDatabase
    """The database as provisioning left it, with the restored ledger."""


class RestoreService:
    def __init__(
        self,
        connector: DatabaseConnector,
        client: PostgresClient,
        store: BackupStore,
        backups: BackupService,
        provisioner: DatabaseProvisioner,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        self._connector = connector
        self._client = client
        self._store = store
        self._backups = backups
        self._provisioner = provisioner
        self._clock = clock

    async def restore(
        self,
        plugin: str,
        desired: DesiredDatabase,
        restore: DesiredRestore,
        *,
        version: str,
        app_password: str,
        on_step: Callable[[RestoreStep, StoredBackup | None], None],
    ) -> RestoreOutcome:
        """Replace the database with the backup `restore` names; see the module.

        `version` is the plugin version whose migrations the database holds now, for the
        pre-restore backup. `on_step` gets each step as it begins, with the pre-restore backup
        once there is one.

        Raises:
            RestoreError: A step failed; `temporary` when it may pass by itself.
        """
        started = time.monotonic()
        step: RestoreStep = "verify"
        try:
            on_step(step, None)
            backup = await self._verify(plugin, desired, restore)
            step = "backup"
            on_step(step, None)
            pre_restore = await self._pre_restore_backup(plugin, desired, restore, version)
            step = "close"
            on_step(step, pre_restore)
            async with self._connector.admin_session(desired.server) as admin:
                await self._close(admin, desired)
                step = "recreate"
                on_step(step, pre_restore)
                await _recreate(admin, desired)
                step = "restore"
                on_step(step, pre_restore)
                await self._restore_as_owner(admin, desired, backup)
                step = "settings"
                on_step(step, pre_restore)
                skipped = await apply_database_settings(admin, desired, backup.metadata.settings())
            if skipped:
                logger.warning(
                    "plugins.database.settings_skipped plugin={} count={}", plugin, skipped
                )
            step = "assert"
            on_step(step, pre_restore)
            provisioned = await self._assert(plugin, desired, app_password)
        except RestoreError as error:
            _log_failure(
                plugin, restore.restore_id, error.step, "temporary" if error.temporary else "failed"
            )
            raise
        except DatabaseUnreachableError as error:
            _log_failure(plugin, restore.restore_id, step, "unreachable")
            raise RestoreError(step, str(error), temporary=True) from None
        except (DatabaseProvisioningError, BackupError, PostgresToolError) as error:
            _log_failure(plugin, restore.restore_id, step, "failed")
            raise RestoreError(step, str(error)) from None
        logger.info(
            "plugins.database.restored plugin={} restore={} step={} duration_ms={}",
            plugin,
            restore.restore_id,
            step,
            round((time.monotonic() - started) * 1000),
        )
        return RestoreOutcome(pre_restore=pre_restore, provisioned=provisioned)

    async def _verify(
        self, plugin: str, desired: DesiredDatabase, restore: DesiredRestore
    ) -> StoredBackup:
        backup = await asyncio.to_thread(self._store.find, plugin, restore.backup_file)
        if backup is None:
            raise RestoreError("verify", f"the node holds no complete backup {restore.backup_file}")
        metadata = backup.metadata
        if (metadata.installation_id, metadata.database_name) != (
            desired.installation_id,
            desired.database_name,
        ):
            raise RestoreError(
                "verify", f"{restore.backup_file} is a backup of another installation"
            )
        sha256 = await asyncio.to_thread(_sha256_of, backup.path)
        if sha256 != restore.backup_sha256 or sha256 != metadata.sha256:
            raise RestoreError("verify", f"{restore.backup_file} does not match its sha256")
        try:
            await check_archive(self._client, backup.path)
        except PostgresToolError as error:
            raise RestoreError("verify", f"{restore.backup_file} cannot be read: {error}") from None
        return backup

    async def _pre_restore_backup(
        self, plugin: str, desired: DesiredDatabase, restore: DesiredRestore, version: str
    ) -> StoredBackup:
        inventory = await asyncio.to_thread(self._store.inventory, plugin)
        taken = next(
            (
                backup
                for backup in inventory
                if backup.metadata.reason == "pre_restore"
                and backup.metadata.restore_id == restore.restore_id
                and backup.metadata.installation_id == desired.installation_id
            ),
            None,
        )
        if taken is not None:
            return taken
        try:
            return await self._backups.backup(
                BackupRequest(
                    plugin=plugin,
                    database=desired,
                    upgrade_id=restore.upgrade_id,
                    reason="pre_restore",
                    version=version,
                    restore_id=restore.restore_id,
                )
            )
        except BackupError as error:
            raise RestoreError("backup", f"the backup before the restore failed: {error}") from None

    async def _close(self, admin: psycopg.AsyncConnection, desired: DesiredDatabase) -> None:
        found = await find_installation(admin, desired)
        if not found.is_ours(desired):
            raise RestoreError(
                "close",
                f"plugins_db has {found.found_objects(desired) or 'nothing'} under this plugin's "
                "names that this installation did not create; nothing was restored",
            )
        await admin.execute(
            sql.SQL("ALTER ROLE {} NOLOGIN").format(sql.Identifier(desired.app_role))
        )
        remaining = await end_sessions(
            admin, [desired.app_role, desired.owner_role], within_seconds=SESSIONS_END_SECONDS
        )
        if remaining:
            raise RestoreError(
                "close",
                f"{len(remaining)} session(s) of the plugin's roles did not end within "
                f"{SESSIONS_END_SECONDS:.0f} s",
            )

    async def _restore_as_owner(
        self, admin: psycopg.AsyncConnection, desired: DesiredDatabase, backup: StoredBackup
    ) -> None:
        password = secrets.token_urlsafe(32)
        await open_owner_login(
            admin, desired.owner_role, password, self._clock() + OWNER_LOGIN_WINDOW
        )
        try:
            await self._client.run(
                "pg_restore",
                RESTORE_ARGUMENTS,
                login=ToolLogin(
                    server=desired.server,
                    database=desired.database_name,
                    user=desired.owner_role,
                    password=password,
                    options=RESTORE_SESSION_OPTIONS,
                    application_name=RESTORE_APPLICATION_NAME,
                ),
                stdin=backup.path,
            )
        except BaseException as failure:
            # The restore's own failure is the one to report; the owner is closed all the same.
            try:
                await close_owner_login(admin, desired.owner_role)
            except (psycopg.Error, DatabaseProvisioningError) as error:
                logger.warning(
                    "Could not close the owner {} after a failed restore: {}",
                    desired.owner_role,
                    describe_error(error) if isinstance(error, psycopg.Error) else error,
                )
            if isinstance(failure, PostgresToolError):
                raise RestoreError("restore", str(failure)) from None
            raise
        await close_owner_login(admin, desired.owner_role)

    async def _assert(
        self, plugin: str, desired: DesiredDatabase, app_password: str
    ) -> ProvisionedDatabase:
        try:
            return await self._provisioner.ensure(plugin, desired, app_password, ())
        except DatabaseProvisioningError as error:
            raise RestoreError("assert", str(error)) from None


async def _recreate(admin: psycopg.AsyncConnection, desired: DesiredDatabase) -> None:
    database = sql.Identifier(desired.database_name)
    await reset_database_attributes(admin, desired.database_name, desired.owner_role)
    # DROP and CREATE DATABASE cannot run inside a transaction: the admin session autocommits.
    await admin.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(desired.owner_role)))
    try:
        await admin.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(database))
    except errors.ObjectInUse as error:
        raise RestoreError(
            "recreate",
            f"database {desired.database_name} is still in use by another session; the node "
            f"tries again: {describe_error(error)}",
            temporary=True,
        ) from None
    finally:
        if not admin.broken:
            await admin.execute("RESET ROLE")
    await admin.execute(
        sql.SQL("CREATE DATABASE {} OWNER {} TEMPLATE template0 ENCODING 'UTF8'").format(
            database, sql.Identifier(desired.owner_role)
        )
    )
    await grant_connect(admin, desired)


def _sha256_of(path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as backup:
        while chunk := backup.read(_HASH_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def _log_failure(
    plugin: str, restore_id: int, step: str, reason: Literal["temporary", "failed", "unreachable"]
) -> None:
    logger.error(
        "plugins.database.restore_failed plugin={} restore={} step={} reason={}",
        plugin,
        restore_id,
        step,
        reason,
    )
