"""Helpers for the tests that run against a plugins_db server (marker `postgres`).

The server is the one `src/plugins_db/lab/run.sh` starts with the real init script and
`pg_hba.conf`; it is named by `ES_PLUGINS_TEST_PG_HOST`, `_PORT`, `_ADMIN_PASSWORD` and
`_BACKUP_PASSWORD`. Every test uses plugins of its own random identifiers and drops what it made,
so tests share the server. The backup and restore tests run that server's own PostgreSQL client
tools (`postgres_client_root`).
"""

import contextlib
import os
import secrets
import shutil
import subprocess
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
    """Remove what provisioning (or a test) made for `desired`: the database of that name and
    every other database the owner owns, then the roles. Its sessions must be closed."""
    connector = DatabaseConnector(admin_password())
    async with connector.admin_session(desired.server) as admin:
        cursor = await admin.execute(
            "SELECT datname, pg_catalog.pg_get_userbyid(datdba) FROM pg_catalog.pg_database "
            "WHERE datname = %s OR datdba = (SELECT oid FROM pg_catalog.pg_roles WHERE rolname = %s)",
            (desired.database_name, desired.owner_role),
        )
        for name, owner in await cursor.fetchall():
            if owner != "plugins_admin":
                await admin.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(owner)))
            await admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))
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


def backup_password() -> str:
    """`plugins_backup`'s password on the test server (`ES_PLUGINS_TEST_PG_BACKUP_PASSWORD`).

    A test that needs it fails without it rather than skip: the lab always sets it.
    """
    return os.environ["ES_PLUGINS_TEST_PG_BACKUP_PASSWORD"]


_TOOL_SHIM = """#!/bin/sh
# {tool} of the test server's own container (PostgreSQL 17), run there with this run's variables;
# archives go through standard input and output, as the node passes them.
{exports}exec '{docker}' exec -i \\
  -e PGUSER -e PGPASSWORD -e PGDATABASE -e PGOPTIONS -e PGAPPNAME -e PGREQUIREAUTH \\
  -e PGCONNECT_TIMEOUT -e PGPASSFILE -e PGSERVICEFILE -e PGHOST=127.0.0.1 -e PGPORT=5432 \\
  '{container}' /usr/lib/postgresql/17/bin/{tool} "$@"
"""


def postgres_client_root(directory) -> "Path":
    """A directory holding `bin/pg_dump` and `bin/pg_restore` of PostgreSQL 17 for the tests.

    `ES_PLUGINS_TEST_PG_CLIENT_ROOT` names one where the tools are installed (the node's image
    has them in /opt/postgresql-client/17). Otherwise they run in the container that publishes
    the test server's port, the lab's plugins_db, through `docker exec`.
    """
    from pathlib import Path

    root = os.environ.get("ES_PLUGINS_TEST_PG_CLIENT_ROOT")
    if root:
        return Path(root)
    docker = shutil.which("docker")
    assert docker, "the Postgres tests need docker, or ES_PLUGINS_TEST_PG_CLIENT_ROOT"
    published = f"{plugins_db_server().host}:{plugins_db_server().port}->5432/tcp"
    listing = subprocess.run(
        [docker, "ps", "--format", "{{.Names}} {{.Ports}}"], capture_output=True, text=True, check=True
    ).stdout
    container = next((line.split(" ", 1)[0] for line in listing.splitlines() if published in line), None)
    assert container, f"no container publishes {published}"
    # The tools run with the node's environment, which has no HOME: docker needs the caller's.
    exports = "".join(
        f"export {name}='{os.environ[name]}'\n"
        for name in ("HOME", "DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_CONFIG")
        if os.environ.get(name)
    )
    bin_directory = Path(directory) / "bin"
    bin_directory.mkdir(parents=True, exist_ok=True)
    for tool in ("pg_dump", "pg_restore"):
        shim = bin_directory / tool
        shim.write_text(_TOOL_SHIM.format(tool=tool, exports=exports, docker=docker, container=container))
        shim.chmod(0o755)
    return Path(directory)


class FreeSpace:
    """`os.statvfs` of a node volume with `free_bytes` free."""

    def __init__(self, free_bytes: int = 64 * 1024**3):
        self.free_bytes = free_bytes

    def __call__(self, path):
        from types import SimpleNamespace

        return SimpleNamespace(f_bavail=self.free_bytes // 4096, f_frsize=4096, f_favail=10**7, f_files=10**8)


def backup_services(layout, client_root, *, free_bytes: int = 64 * 1024**3, connect=None, create_process=None):
    """A real `BackupService` and `RestoreService` on the test server, keeping backups in `layout`."""
    from es_plugins.database.backup_service import BackupService
    from es_plugins.database.backup_store import BackupStore
    from es_plugins.database.postgres_client import PostgresClient
    from es_plugins.database.provisioner import DatabaseProvisioner
    from es_plugins.database.restore_service import RestoreService
    from es_plugins.node_disk import NodeDisk

    layout.backups_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    connector = DatabaseConnector(admin_password(), **({"connect": connect} if connect else {}))
    client = PostgresClient(client_root, **({"create_process": create_process} if create_process else {}))
    store = BackupStore(layout)
    backups = BackupService(
        connector, client, store, NodeDisk(layout.data_root, statvfs=FreeSpace(free_bytes)), backup_password()
    )
    restores = RestoreService(connector, client, store, backups, DatabaseProvisioner(connector))
    return backups, restores, store
