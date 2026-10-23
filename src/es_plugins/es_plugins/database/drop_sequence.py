"""Drop a removed plugin's database and its three roles from plugins_db, for good.

`DatabaseDropper.drop` runs these steps, every one on an admin session to `postgres`
(`plugins_admin` never connects to a plugin's database, and no SQL the plugin wrote runs):

1. **Marker check** (`installation_lookup`). Nothing of the plugin's names there: done, nothing
   dropped. This installation's roles and database: go on. Anything else is a `conflict`, and
   nothing is changed: those roles or that database are another installation's data.
2. **No more logins**: the app role and the owner become NOLOGIN.
3. **No more connections**: when the database exists, its owner revokes CONNECT from the app and
   job roles.
4. **Sessions ended**: every session logged in as the app role (those that switched to the job
   role included) or as the owner, through `plugins_admin`'s `pg_signal_backend`. A session that
   is still there after 10 s is a permanent `database` failure. Sessions of other roles, a backup
   among them, are never ended.
5. **Databases**: every database the owner owns is dropped as the owner, without FORCE, after its
   template mark and connection limit are put back (`database_attributes`: `DROP DATABASE`
   refuses a template, and the owner may have made it one). A session still connected, a backup
   in practice, makes PostgreSQL refuse (SQLSTATE 55006): a temporary failure, tried again later.
6. **Other databases**: nothing in another database may still refer to one of the three roles
   (`pg_shdepend`). Another plugin can grant on its own tables to this plugin's app role, and
   PostgreSQL then refuses to drop it; the failure names that database, and is permanent.
7. **Roles**: the three, in one statement.
8. **Checks**: no role of the three and no database of the owner is left, and `plugins_admin`
   holds no membership it granted itself with INHERIT.

Every step can run again: a drop that stopped half-way, or one already finished, picks up where
the server is.
"""

from dataclasses import dataclass
from typing import Literal

import psycopg
from psycopg import errors, sql
from src.shared.models.plugin_nodes import DesiredDatabase

from es_plugins.database.connections import (
    ADMIN_ROLE,
    DatabaseConnector,
    DatabaseProvisioningError,
    describe_error,
    describe_text,
    end_sessions,
)
from es_plugins.database.database_attributes import reset_database_attributes
from es_plugins.database.installation_lookup import find_installation

SESSIONS_END_SECONDS = 10.0
REFERENCED_ELSEWHERE_MESSAGE = (
    "{databases} still refer to this plugin's roles (another plugin granted access to them or "
    "named them in a policy), so the node cannot delete the roles. Remove those references in "
    "that plugin (see the operator guide), then press Retry removal."
)
REMOVAL_CONFLICT_MESSAGE = (
    "plugins_db has {objects} that this plugin installation did not create, probably left from "
    "another EpicStaff database, and the node will not delete them. Remove them (see the operator "
    "guide), then press Retry removal."
)
_OWNED_DATABASES = (
    "SELECT datname FROM pg_catalog.pg_database "
    "WHERE datdba = (SELECT oid FROM pg_catalog.pg_roles WHERE rolname = %s) ORDER BY datname"
)
# Dependencies on the roles recorded under another database (dbid 0 is the cluster's own objects).
_REFERENCES_ELSEWHERE = (
    "SELECT DISTINCT d.datname FROM pg_catalog.pg_shdepend s "
    "JOIN pg_catalog.pg_database d ON d.oid = s.dbid "
    "WHERE s.refclassid = 'pg_catalog.pg_authid'::pg_catalog.regclass "
    "AND s.refobjid IN (SELECT oid FROM pg_catalog.pg_roles WHERE rolname = ANY(%s)) "
    "ORDER BY d.datname LIMIT 10"
)
_SELF_GRANTED_INHERIT = (
    "SELECT r.rolname FROM pg_catalog.pg_auth_members m "
    "JOIN pg_catalog.pg_roles r ON r.oid = m.roleid "
    "JOIN pg_catalog.pg_roles u ON u.oid = m.member "
    "WHERE u.rolname = %s AND m.grantor = m.member AND m.inherit_option ORDER BY r.rolname"
)


class DatabaseDropError(Exception):
    """The drop failed; `temporary` failures may pass if tried again later.

    `conflict`: the roles or database are not this installation's, and nothing was changed.
    `database`: a statement failed or a check did not hold.
    """

    def __init__(
        self, reason: Literal["conflict", "database"], message: str, *, temporary: bool = False
    ):
        super().__init__(message)
        self.reason = reason
        self.temporary = temporary


@dataclass(frozen=True)
class DroppedDatabase:
    databases: int
    roles: int


class DatabaseDropper:
    def __init__(self, connector: DatabaseConnector):
        self._connector = connector

    async def drop(self, desired: DesiredDatabase) -> DroppedDatabase:
        """Drop the plugin's databases and roles; see the module. The caller holds the
        placement's database lock.

        Raises:
            DatabaseUnreachableError: plugins_db cannot be reached now, or the session was lost.
            DatabaseDropError: A conflict, a session that would not end, a database in use
                (`temporary`), or a statement or check that failed.
        """
        try:
            async with self._connector.admin_session(desired.server) as admin:
                return await self._drop(admin, desired)
        except DatabaseProvisioningError as error:
            # A statement the session wrapper classified; the drop names its own reasons.
            raise DatabaseDropError("database", str(error)) from None

    async def _drop(
        self, admin: psycopg.AsyncConnection, desired: DesiredDatabase
    ) -> DroppedDatabase:
        found = await find_installation(admin, desired)
        if found.absent:
            return DroppedDatabase(databases=0, roles=0)
        if not found.is_ours(desired):
            raise DatabaseDropError(
                "conflict", REMOVAL_CONFLICT_MESSAGE.format(objects=found.found_objects(desired))
            )
        roles = [
            name
            for name in (desired.app_role, desired.job_role, desired.owner_role)
            if name in found.roles
        ]
        cursor = await admin.execute(_OWNED_DATABASES, (desired.owner_role,))
        databases = [row[0] for row in await cursor.fetchall()]

        for role in (desired.app_role, desired.owner_role):
            if role in found.roles:
                await admin.execute(sql.SQL("ALTER ROLE {} NOLOGIN").format(sql.Identifier(role)))
        if found.database_owner is not None:
            await _revoke_connect(admin, desired, found.roles)
        logged_in = [role for role in (desired.app_role, desired.owner_role) if role in found.roles]
        remaining = await end_sessions(admin, logged_in, within_seconds=SESSIONS_END_SECONDS)
        if remaining:
            raise DatabaseDropError(
                "database",
                f"{len(remaining)} session(s) of the plugin's roles did not end within "
                f"{SESSIONS_END_SECONDS:.0f} s",
            )
        for database in databases:
            await reset_database_attributes(admin, database, desired.owner_role)
            await _drop_database(admin, desired.owner_role, database)
        await _check_not_referenced_elsewhere(admin, roles)
        try:
            await admin.execute(
                sql.SQL("DROP ROLE IF EXISTS {}").format(
                    sql.SQL(", ").join(sql.Identifier(role) for role in roles)
                )
            )
        except errors.DependentObjectsStillExist as error:
            # A reference made since the check above. PostgreSQL's detail names the database.
            await _check_not_referenced_elsewhere(admin, roles)
            detail = describe_text(error.diag.message_detail or "")
            raise DatabaseDropError(
                "database",
                f"the plugin's roles are still referred to elsewhere: {describe_error(error)}"
                + (f" ({detail})" if detail else ""),
            ) from None
        await _check_nothing_is_left(admin, desired, databases)
        return DroppedDatabase(databases=len(databases), roles=len(roles))


async def _revoke_connect(
    admin: psycopg.AsyncConnection, desired: DesiredDatabase, existing_roles: frozenset[str]
) -> None:
    revoked = [role for role in (desired.app_role, desired.job_role) if role in existing_roles]
    if not revoked:
        return
    # As the owner: privileges on its database are the owner's to revoke. SET LOCAL ends with
    # the transaction, whichever way it ends.
    async with admin.transaction():
        await admin.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(desired.owner_role)))
        await admin.execute(
            sql.SQL("REVOKE CONNECT ON DATABASE {} FROM {}").format(
                sql.Identifier(desired.database_name),
                sql.SQL(", ").join(sql.Identifier(role) for role in revoked),
            )
        )


async def _drop_database(admin: psycopg.AsyncConnection, owner_role: str, database: str) -> None:
    """Drop `database` as its owner; DROP DATABASE cannot run inside a transaction."""
    await admin.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(owner_role)))
    try:
        await admin.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(database)))
    except errors.ObjectInUse as error:
        raise DatabaseDropError(
            "database",
            f"database {database} is still in use by another session, a backup perhaps; "
            f"the node tries again: {describe_error(error)}",
            temporary=True,
        ) from None
    finally:
        if not admin.broken:
            await admin.execute("RESET ROLE")


async def _check_not_referenced_elsewhere(admin: psycopg.AsyncConnection, roles: list[str]) -> None:
    """Raises: DatabaseDropError: another database refers to one of the roles (permanent)."""
    cursor = await admin.execute(_REFERENCES_ELSEWHERE, (roles,))
    databases = [row[0] for row in await cursor.fetchall()]
    if databases:
        raise DatabaseDropError(
            "database",
            REFERENCED_ELSEWHERE_MESSAGE.format(
                databases=", ".join(f'database "{name}"' for name in databases)
            ),
        )


async def _check_nothing_is_left(
    admin: psycopg.AsyncConnection, desired: DesiredDatabase, dropped: list[str]
) -> None:
    names = [desired.owner_role, desired.app_role, desired.job_role]
    cursor = await admin.execute(
        "SELECT rolname FROM pg_catalog.pg_roles WHERE rolname = ANY(%s)", (names,)
    )
    roles_left = [row[0] for row in await cursor.fetchall()]
    cursor = await admin.execute(
        "SELECT datname FROM pg_catalog.pg_database WHERE datname = ANY(%s)",
        ([desired.database_name, *dropped],),
    )
    databases_left = [row[0] for row in await cursor.fetchall()]
    cursor = await admin.execute(_SELF_GRANTED_INHERIT, (ADMIN_ROLE,))
    inherited = [row[0] for row in await cursor.fetchall()]
    problems = [
        *(f"role {name} is still there" for name in roles_left),
        *(f"database {name} is still there" for name in databases_left),
        *(f"{ADMIN_ROLE} inherits {name} through a grant of its own" for name in inherited),
    ]
    if problems:
        raise DatabaseDropError("database", "after the drop: " + "; ".join(problems))
