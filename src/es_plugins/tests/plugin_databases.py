"""Helpers for the tests that run against a plugins_db server (marker `postgres`).

The server is the one `src/plugins_db/lab/run.sh` starts with the real init script and
`pg_hba.conf`; it is named by `ES_PLUGINS_TEST_PG_HOST`, `_PORT` and `_ADMIN_PASSWORD`. Every test
uses plugins of its own random identifiers and drops what it made, so tests share the server.
"""

import contextlib
import os
import secrets
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import psycopg
from psycopg import sql
from src.shared.models.plugin_nodes import (
    DesiredDatabase,
    DesiredDatabaseServer,
    database_names_for,
)

from es_plugins.database.connections import REQUIRED_AUTHENTICATION, DatabaseConnector
from es_plugins.database.migration_runner import close_owner_login, open_owner_login


def plugins_db_server() -> DesiredDatabaseServer:
    return DesiredDatabaseServer(
        name="plugins_db",
        host=os.environ["ES_PLUGINS_TEST_PG_HOST"],
        port=int(os.environ["ES_PLUGINS_TEST_PG_PORT"]),
    )


def admin_password() -> str:
    return os.environ["ES_PLUGINS_TEST_PG_ADMIN_PASSWORD"]


def new_identifier(stem: str = "t") -> str:
    """A plugin identifier no other test uses; with `-` in it, as many identifiers have."""
    return f"{stem}{secrets.token_hex(3)}-x"


def new_app_password() -> str:
    """43 URL-safe characters, as django_app generates them."""
    return secrets.token_urlsafe(32)


def desired_database(
    identifier: str,
    *,
    installation_id: str | None = None,
    connection_limit: int = 3,
    statement_timeout_seconds: int = 10,
) -> DesiredDatabase:
    names = database_names_for(identifier)
    return DesiredDatabase(
        server=plugins_db_server(),
        installation_id=installation_id or uuid.uuid4().hex,
        database_name=names.database,
        owner_role=names.owner_role,
        app_role=names.app_role,
        job_role=names.job_role,
        connection_limit=connection_limit,
        statement_timeout_seconds=statement_timeout_seconds,
    )


async def connect_as(
    role: str, password: str, database_name: str, **parameters
) -> psycopg.AsyncConnection:
    server = plugins_db_server()
    return await psycopg.AsyncConnection.connect(
        host=server.host,
        port=server.port,
        dbname=database_name,
        user=role,
        password=password,
        require_auth=REQUIRED_AUTHENTICATION,
        connect_timeout=10,
        autocommit=True,
        **parameters,
    )


async def drop_plugin_database(desired: DesiredDatabase) -> None:
    """Remove what provisioning (or a test) made for `desired`; its sessions must be closed."""
    connector = DatabaseConnector(admin_password())
    async with connector.admin_session(desired.server) as admin:
        cursor = await admin.execute(
            "SELECT pg_catalog.pg_get_userbyid(datdba) FROM pg_catalog.pg_database WHERE datname = %s",
            (desired.database_name,),
        )
        owner = await cursor.fetchone()
        if owner is not None:
            if owner[0] != "plugins_admin":
                await admin.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(owner[0])))
            await admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(desired.database_name)))
            await admin.execute("RESET ROLE")
        for role in (desired.app_role, desired.job_role, desired.owner_role):
            await admin.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(role)))


class ConnectionSpy:
    """psycopg's `connect`, recording each connection's parameters and every statement sent."""

    def __init__(self):
        self.connections: list[dict] = []
        self.statements: list[str] = []
        statements = self.statements

        class RecordingCursor(psycopg.AsyncCursor):
            async def execute(self, query, params=None, **arguments):
                text = query.as_string(self.connection) if isinstance(query, sql.Composable) else query
                statements.append(text)
                return await super().execute(query, params, **arguments)

        self._cursor_factory = RecordingCursor

    async def __call__(self, **parameters) -> psycopg.AsyncConnection:
        self.connections.append({key: value for key, value in parameters.items() if key != "password"})
        return await psycopg.AsyncConnection.connect(cursor_factory=self._cursor_factory, **parameters)


async def catalog_snapshot(desired: DesiredDatabase) -> dict:
    """Everything provisioning sets, as plugins_admin can read it from `postgres`."""
    connector = DatabaseConnector(admin_password())
    roles = [desired.owner_role, desired.app_role, desired.job_role]
    async with connector.admin_session(desired.server) as admin:
        queries = {
            "roles": (
                "SELECT rolname, rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls, "
                "rolcanlogin, rolconnlimit, rolvaliduntil::text FROM pg_roles WHERE rolname = ANY(%s) ORDER BY 1",
                (roles,),
            ),
            "memberships": (
                "SELECT r.rolname, m.rolname, am.admin_option, am.inherit_option, am.set_option "
                "FROM pg_auth_members am JOIN pg_roles r ON r.oid = am.roleid JOIN pg_roles m ON m.oid = am.member "
                "WHERE r.rolname = ANY(%s) OR m.rolname = ANY(%s) ORDER BY 1, 2, 3, 4, 5",
                (roles, roles),
            ),
            "marker": (
                "SELECT d.description FROM pg_shdescription d JOIN pg_roles r ON r.oid = d.objoid "
                "WHERE d.classoid = 'pg_authid'::regclass AND r.rolname = %s",
                (desired.owner_role,),
            ),
            "database": (
                "SELECT datname, pg_get_userbyid(datdba), datacl::text[] FROM pg_database WHERE datname = %s",
                (desired.database_name,),
            ),
            "settings": (
                "SELECT setdatabase, setconfig FROM pg_db_role_setting "
                "WHERE setrole = (SELECT oid FROM pg_roles WHERE rolname = %s) ORDER BY 1",
                (desired.app_role,),
            ),
        }
        snapshot = {}
        for name, (query, parameters) in queries.items():
            cursor = await admin.execute(query, parameters)
            snapshot[name] = await cursor.fetchall()
        return snapshot


@contextlib.asynccontextmanager
async def owner_session(desired: DesiredDatabase) -> AsyncIterator[psycopg.AsyncConnection]:
    """A session as the plugin's owner on its database, opened and closed as the runner does."""
    connector = DatabaseConnector(admin_password())
    password = secrets.token_urlsafe(32)
    async with connector.admin_session(desired.server) as admin:
        await open_owner_login(
            admin, desired.owner_role, password, datetime.now(UTC) + timedelta(minutes=5)
        )
        try:
            async with connector.owner_session(
                desired.server, desired.database_name, desired.owner_role, password
            ) as owner:
                yield owner
        finally:
            await close_owner_login(admin, desired.owner_role)


async def fetch_all(connection: psycopg.AsyncConnection, query, parameters=None) -> list[tuple]:
    cursor = await connection.execute(query, parameters)
    return await cursor.fetchall()
