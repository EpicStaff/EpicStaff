"""Create, or adopt, a placement's plugin database on plugins_db, and migrate it.

`DatabaseProvisioner.ensure` runs these steps, every one on an admin session to `postgres`:

1. **Conflict check** (`installation_lookup`). Nothing found: create. This installation's
   roles and database: adopt. Anything else is a `conflict`, and nothing is changed.
2. **Roles**, in one transaction. Created NOLOGIN (the app role LOGIN, with its password's
   SCRAM verifier and its connection limit) with every privilege attribute off, the marker on
   the owner; adopted ones are set back to the same LOGIN, CREATEDB and CREATEROLE attributes,
   password and limit (a SUPERUSER, REPLICATION or BYPASSRLS attribute is only checked: only a
   superuser may even switch it off). Then `plugins_admin` gets SET, without INHERIT, on the
   owner, and the app role SET, without INHERIT, on the job role.
3. **Database**, when it is missing: `plugin_<id_>`, owned by the owner, from `template0`.
4. **CONNECT**, in one transaction as the owner (a REVOKE by `plugins_admin` itself would be a
   silent no-op): PUBLIC loses it, the five roles of `connect_holders` get it.
5. **Limits** (`apply_app_limits`).
6. **Assertions** (`ProvisioningAssertions.check`).
7. **Migrations** (`MigrationRunner`), with the owner as the session user.
8. **Permissions again**: a migration runs as the owner, which may grant on its own database.
9. The database's size, and the log line `plugins.database.provisioned`.

Every step is idempotent: provisioning a ready database again changes nothing but the app role's
stored verifier (a new salt for the same password). The whole run is bounded by
`PROVISIONING_TIMEOUT`; one that takes longer fails as a `migration` failure, and a statement still
running on the server is cancelled there too. plugins_db not answering is logged once per outage.
"""

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import Literal

import psycopg
from loguru import logger
from psycopg import sql
from src.shared.models.plugin_nodes import DesiredDatabase

from es_plugins.database.app_role_limits import apply_app_limits
from es_plugins.database.connections import (
    ADMIN_ROLE,
    DatabaseConnector,
    DatabaseProvisioningError,
    DatabaseUnreachableError,
    scram_verifier,
)
from es_plugins.database.installation_lookup import (
    InstallationFootprint,
    find_installation,
    installation_marker,
)
from es_plugins.database.migration_runner import OWNER_LOGIN_WINDOW, Migration, MigrationRunner
from es_plugins.database.provisioning_assertions import ProvisioningAssertions, connect_holders

# The owner may log in for OWNER_LOGIN_WINDOW; the minute after it covers the steps around the run.
PROVISIONING_TIMEOUT = OWNER_LOGIN_WINDOW + timedelta(minutes=1)
CONFLICT_MESSAGE = (
    "plugins_db already has {objects} that this plugin installation did not create, probably "
    "left from another EpicStaff database. Remove them (see the operator guide) or restore the "
    "matching EpicStaff database, then press Restart."
)
_NO_PRIVILEGES = sql.SQL("NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS")
# What `plugins_admin` may set on a role it administers; the other attributes need a superuser.
_RESETTABLE_PRIVILEGES = sql.SQL("NOCREATEDB NOCREATEROLE")


@dataclass(frozen=True)
class ProvisionedDatabase:
    created: bool
    """Whether this call created the database (rather than finding it)."""

    ledger: tuple[str, ...]
    """The migrations applied to it, in the order they were applied."""

    applied: int
    """How many migrations this call applied."""

    size_bytes: int


class DatabaseProvisioner:
    def __init__(
        self,
        connector: DatabaseConnector,
        *,
        assertions: ProvisioningAssertions | None = None,
        runner: MigrationRunner | None = None,
    ):
        self._connector = connector
        self._assertions = assertions or ProvisioningAssertions()
        self._runner = runner or MigrationRunner(connector)
        # The plugins whose last attempt found plugins_db unreachable: logged once per outage.
        self._unreachable: set[str] = set()

    async def ensure(
        self,
        plugin: str,
        desired: DesiredDatabase,
        app_password: str,
        migrations: Sequence[Migration],
    ) -> ProvisionedDatabase:
        """Bring the plugin's database to `desired` and apply its migrations; see the module.

        The caller holds the placement's database lock, so the limits watchdog leaves the
        database alone meanwhile.

        Raises:
            DatabaseUnreachableError: plugins_db cannot be reached now (transient).
            DatabaseProvisioningError: A conflict, an assertion, a migration or another
                statement failed (permanent), or it took longer than `PROVISIONING_TIMEOUT`
                (reason `migration`); nothing more was attempted.
        """
        try:
            async with asyncio.timeout(PROVISIONING_TIMEOUT.total_seconds()):
                created_database, run, size_bytes = await self._provision(
                    desired, app_password, migrations
                )
        except TimeoutError:
            error = DatabaseProvisioningError(
                "migration",
                f"provisioning the database did not finish within "
                f"{PROVISIONING_TIMEOUT.total_seconds() / 60:.0f} minutes",
            )
            self._unreachable.discard(plugin)
            log_database_failure(plugin, error.reason, str(error))
            raise error from None
        except DatabaseUnreachableError as error:
            if plugin not in self._unreachable:
                self._unreachable.add(plugin)
                log_database_failure(plugin, "unreachable", str(error))
            raise
        except DatabaseProvisioningError as error:
            self._unreachable.discard(plugin)
            log_database_failure(plugin, error.reason, str(error))
            raise
        self._unreachable.discard(plugin)
        logger.info(
            "plugins.database.provisioned plugin={} database={} created={} migrations_applied={}",
            plugin,
            desired.database_name,
            "true" if created_database else "false",
            run.applied,
        )
        return ProvisionedDatabase(
            created=created_database, ledger=run.ledger, applied=run.applied, size_bytes=size_bytes
        )

    async def _provision(
        self, desired: DesiredDatabase, app_password: str, migrations: Sequence[Migration]
    ):
        async with self._connector.admin_session(desired.server) as admin:
            found = await find_installation(admin, desired)
            create = _choose_path(found, desired) == "create"
            await _ensure_roles(admin, desired, app_password, found, create=create)
            created_database = found.database_owner is None
            if created_database:
                await admin.execute(
                    sql.SQL(
                        "CREATE DATABASE {} OWNER {} TEMPLATE template0 ENCODING 'UTF8'"
                    ).format(
                        sql.Identifier(desired.database_name),
                        sql.Identifier(desired.owner_role),
                    )
                )
            await _grant_connect(admin, desired)
            await apply_app_limits(admin, desired)
            await self._assertions.check(admin, desired)
            run = await self._runner.run(admin, desired, migrations)
            # The migrations ran as the owner, which may grant on its own database.
            problems = await self._assertions.permission_problems(admin, desired)
            if problems:
                raise DatabaseProvisioningError(
                    "assertion",
                    "the plugin database's permissions changed during its migrations: "
                    + "; ".join(problems),
                )
            size_bytes = await database_size(admin, desired.database_name)
        return created_database, run, size_bytes


def log_database_failure(plugin: str, reason: str, detail: str) -> None:
    logger.error("plugins.database.failed plugin={} reason={} detail={}", plugin, reason, detail)


async def database_size(admin: psycopg.AsyncConnection, database_name: str) -> int:
    cursor = await admin.execute("SELECT pg_catalog.pg_database_size(%s)", (database_name,))
    return (await cursor.fetchone())[0]


def _choose_path(
    found: InstallationFootprint, desired: DesiredDatabase
) -> Literal["create", "adopt"]:
    """Raises: DatabaseProvisioningError: reason `conflict`."""
    if found.absent:
        return "create"
    if found.is_ours(desired):
        return "adopt"
    raise DatabaseProvisioningError(
        "conflict", CONFLICT_MESSAGE.format(objects=found.found_objects(desired))
    )


async def _ensure_roles(
    admin: psycopg.AsyncConnection,
    desired: DesiredDatabase,
    app_password: str,
    found: InstallationFootprint,
    *,
    create: bool,
) -> None:
    owner = sql.Identifier(desired.owner_role)
    app = sql.Identifier(desired.app_role)
    job = sql.Identifier(desired.job_role)
    app_login = sql.SQL("LOGIN PASSWORD {} CONNECTION LIMIT {}").format(
        sql.Literal(scram_verifier(admin, desired.app_role, app_password)),
        sql.Literal(desired.connection_limit),
    )
    roles = (
        (desired.owner_role, owner, sql.SQL("NOLOGIN")),
        (desired.job_role, job, sql.SQL("NOLOGIN")),
        (desired.app_role, app, app_login),
    )
    async with admin.transaction():
        for name, identifier, login in roles:
            if name in found.roles:
                statement = sql.SQL("ALTER ROLE {} {} {}").format(
                    identifier, login, _RESETTABLE_PRIVILEGES
                )
            else:
                statement = sql.SQL("CREATE ROLE {} {} {}").format(
                    identifier, login, _NO_PRIVILEGES
                )
            await admin.execute(statement)
        if create:
            await admin.execute(
                sql.SQL("COMMENT ON ROLE {} IS {}").format(
                    owner, sql.Literal(installation_marker(desired.installation_id))
                )
            )
        await admin.execute(
            sql.SQL("GRANT {} TO {} WITH INHERIT FALSE, SET TRUE").format(
                owner, sql.Identifier(ADMIN_ROLE)
            )
        )
        await admin.execute(sql.SQL("GRANT {} TO {} WITH INHERIT FALSE, SET TRUE").format(job, app))


async def _grant_connect(admin: psycopg.AsyncConnection, desired: DesiredDatabase) -> None:
    database = sql.Identifier(desired.database_name)
    holders = sql.SQL(", ").join(sql.Identifier(name) for name in sorted(connect_holders(desired)))
    # As the owner: privileges on its database are the owner's to revoke. SET LOCAL ends with
    # the transaction, whichever way it ends.
    async with admin.transaction():
        await admin.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(desired.owner_role)))
        await admin.execute(sql.SQL("REVOKE CONNECT ON DATABASE {} FROM PUBLIC").format(database))
        await admin.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(database, holders))
