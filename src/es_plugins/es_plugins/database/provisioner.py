"""Create, or adopt, a placement's plugin database on plugins_db, and migrate it.

`DatabaseProvisioner.ensure` runs these steps, every one on an admin session to `postgres`:

1. **Conflict check.** The three roles, the owner's comment and the database's owner are read.
   The comment is the installation marker, `epicstaff-plugin-installation:<installation id>`.
   Nothing found: create. An owner carrying this installation's marker (and a database, if
   there is one, owned by it): adopt. Anything else is a `conflict`, and nothing is changed:
   adopting a database left from another EpicStaff database would show one organization's
   plugin data to another that got the same ids.
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
8. The database's size, and the log line `plugins.database.provisioned`.

Every step is idempotent: provisioning a ready database again changes nothing but the app role's
stored verifier (a new salt for the same password).
"""

from collections.abc import Sequence
from dataclasses import dataclass
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
from es_plugins.database.migration_runner import Migration, MigrationRunner
from es_plugins.database.provisioning_assertions import ProvisioningAssertions, connect_holders

INSTALLATION_MARKER_PREFIX = "epicstaff-plugin-installation:"
CONFLICT_MESSAGE = (
    "plugins_db already has {objects} that this plugin installation did not create, probably "
    "left from another EpicStaff database. Remove them (see the operator guide) or restore the "
    "matching EpicStaff database, then press Restart."
)
_NO_PRIVILEGES = sql.SQL("NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS")
# What `plugins_admin` may set on a role it administers; the other attributes need a superuser.
_RESETTABLE_PRIVILEGES = sql.SQL("NOCREATEDB NOCREATEROLE")
_OWNER_MARKER = (
    "SELECT d.description FROM pg_catalog.pg_shdescription d "
    "JOIN pg_catalog.pg_roles r ON r.oid = d.objoid "
    "WHERE d.classoid = 'pg_catalog.pg_authid'::pg_catalog.regclass AND r.rolname = %s"
)


def installation_marker(installation_id: str) -> str:
    return INSTALLATION_MARKER_PREFIX + installation_id


@dataclass(frozen=True)
class ProvisionedDatabase:
    created: bool
    """Whether this call created the database (rather than finding it)."""

    ledger: tuple[str, ...]
    """The migrations applied to it, in the order they were applied."""

    applied: int
    """How many migrations this call applied."""

    size_bytes: int


@dataclass(frozen=True)
class _Found:
    roles: frozenset[str]
    owner_marker: str | None
    database_owner: str | None
    """Who owns the database of the desired name; None when there is none."""


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
                statement failed (permanent); nothing more was attempted.
        """
        try:
            async with self._connector.admin_session(desired.server) as admin:
                found = await _find(admin, desired)
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
                size_bytes = await database_size(admin, desired.database_name)
        except DatabaseUnreachableError as error:
            log_database_failure(plugin, "unreachable", str(error))
            raise
        except DatabaseProvisioningError as error:
            log_database_failure(plugin, error.reason, str(error))
            raise
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


def log_database_failure(plugin: str, reason: str, detail: str) -> None:
    logger.error("plugins.database.failed plugin={} reason={} detail={}", plugin, reason, detail)


async def database_size(admin: psycopg.AsyncConnection, database_name: str) -> int:
    cursor = await admin.execute("SELECT pg_catalog.pg_database_size(%s)", (database_name,))
    return (await cursor.fetchone())[0]


async def _find(admin: psycopg.AsyncConnection, desired: DesiredDatabase) -> _Found:
    names = [desired.owner_role, desired.app_role, desired.job_role]
    cursor = await admin.execute(
        "SELECT rolname FROM pg_catalog.pg_roles WHERE rolname = ANY(%s)", (names,)
    )
    roles = frozenset(row[0] for row in await cursor.fetchall())
    cursor = await admin.execute(_OWNER_MARKER, (desired.owner_role,))
    marker = await cursor.fetchone()
    cursor = await admin.execute(
        "SELECT pg_catalog.pg_get_userbyid(datdba) FROM pg_catalog.pg_database WHERE datname = %s",
        (desired.database_name,),
    )
    database = await cursor.fetchone()
    return _Found(
        roles=roles,
        owner_marker=marker[0] if marker else None,
        database_owner=database[0] if database else None,
    )


def _choose_path(found: _Found, desired: DesiredDatabase) -> Literal["create", "adopt"]:
    """Raises: DatabaseProvisioningError: reason `conflict`."""
    if not found.roles and found.database_owner is None:
        return "create"
    owner_is_ours = desired.owner_role in found.roles and found.owner_marker == installation_marker(
        desired.installation_id
    )
    if owner_is_ours and found.database_owner in (None, desired.owner_role):
        return "adopt"
    objects = [
        f'role "{name}"'
        for name in (desired.owner_role, desired.app_role, desired.job_role)
        if name in found.roles
    ]
    if found.database_owner is not None:
        objects.append(f'database "{desired.database_name}"')
    raise DatabaseProvisioningError("conflict", CONFLICT_MESSAGE.format(objects=", ".join(objects)))


async def _ensure_roles(
    admin: psycopg.AsyncConnection,
    desired: DesiredDatabase,
    app_password: str,
    found: _Found,
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
