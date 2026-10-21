"""Provisioning a plugin database on a real plugins_db (marker `postgres`), and the node's sessions."""

import asyncio
import socket

import psycopg
import pytest
from loguru import logger
from psycopg import sql
from src.shared.models.plugin_nodes import DesiredDatabase, DesiredDatabaseServer, database_names_for

from es_plugins.database.connections import (
    DatabaseConnector,
    DatabaseProvisioningError,
    DatabaseUnreachableError,
)
from es_plugins.database.migration_runner import Migration
from es_plugins.database.provisioner import DatabaseProvisioner, installation_marker
from tests.plugin_databases import (
    ConnectionSpy,
    admin_password,
    catalog_snapshot,
    connect_as,
    new_app_password,
)

ADMIN = "plugins_admin"


@pytest.fixture
def log_lines():
    lines = []
    sink = logger.add(lambda message: lines.append(message.rstrip("\n")), format="{message}", level="DEBUG")
    yield lines
    logger.remove(sink)


def provisioner(spy: ConnectionSpy | None = None) -> DatabaseProvisioner:
    if spy is None:
        return DatabaseProvisioner(DatabaseConnector(admin_password()))
    return DatabaseProvisioner(DatabaseConnector(admin_password(), connect=spy))


async def as_admin(desired, *statements):
    async with DatabaseConnector(admin_password()).admin_session(desired.server) as admin:
        for statement in statements:
            await admin.execute(statement)


def a_migration(name="001_places.sql", text="CREATE TABLE places (id int);") -> Migration:
    import hashlib

    content = text.encode()
    return Migration(name=name, sha256=hashlib.sha256(content).hexdigest(), content=content)


@pytest.mark.postgres
async def test_a_fresh_database_gets_exactly_the_roles_memberships_privileges_and_settings(
    plugin_databases, log_lines
):
    desired = plugin_databases()
    owner, app, job = desired.owner_role, desired.app_role, desired.job_role

    outcome = await provisioner().ensure("weather", desired, new_app_password(), [])

    assert (outcome.created, outcome.ledger, outcome.applied) == (True, (), 0)
    assert outcome.size_bytes > 0
    snapshot = await catalog_snapshot(desired)
    # rolname, super, createdb, createrole, replication, bypassrls, login, connlimit, valid until
    assert snapshot["roles"] == sorted(
        [
            (app, False, False, False, False, False, True, 3, None),
            (job, False, False, False, False, False, False, -1, None),
            # Closed again after the migration run, even one with nothing to apply.
            (owner, False, False, False, False, False, False, -1, "infinity"),
        ]
    )
    assert snapshot["memberships"] == sorted(
        [
            (app, ADMIN, True, False, False),
            (job, ADMIN, True, False, False),
            (job, app, False, False, True),
            (owner, ADMIN, False, False, True),
            (owner, ADMIN, True, False, False),
        ]
    )
    assert snapshot["marker"] == [(installation_marker(desired.installation_id),)]
    name, database_owner, acl = snapshot["database"][0]
    assert (name, database_owner) == (desired.database_name, owner)
    assert [entry for entry in acl if entry.startswith("=")] == [f"=T/{owner}"]
    connect_holders = {entry.split("=")[0] for entry in acl if "c" in entry.split("=")[1].split("/")[0]}
    assert connect_holders == {owner, app, job, ADMIN, "plugins_backup"}
    assert snapshot["settings"] == [(0, ["statement_timeout=10s"])]
    assert (
        f"plugins.database.provisioned plugin=weather database={desired.database_name} "
        "created=true migrations_applied=0"
    ) in log_lines


@pytest.mark.postgres
async def test_provisioning_again_changes_nothing_but_the_reasserted_password(plugin_databases):
    desired = plugin_databases()
    password = new_app_password()
    await provisioner().ensure("weather", desired, password, [a_migration()])
    before = await catalog_snapshot(desired)
    spy = ConnectionSpy()

    outcome = await provisioner(spy).ensure("weather", desired, password, [a_migration()])

    assert (outcome.created, outcome.ledger, outcome.applied) == (False, ("001_places.sql",), 0)
    assert await catalog_snapshot(desired) == before
    assert not [statement for statement in spy.statements if statement.startswith(("CREATE ROLE", "CREATE DATABASE"))]
    assert [statement for statement in spy.statements if statement.startswith(f'ALTER ROLE "{desired.app_role}" LOGIN PASSWORD')]
    app = await connect_as(desired.app_role, password, desired.database_name)
    await app.close()


@pytest.mark.postgres
async def test_its_own_installation_is_adopted_and_what_a_dead_agent_left_is_repaired(plugin_databases):
    desired = plugin_databases()
    password = new_app_password()
    await provisioner().ensure("weather", desired, password, [])
    # An agent that died in a migration run left the owner able to log in; the app rewrote its
    # own defaults; the database is gone (dropped by hand, say).
    await as_admin(
        desired,
        sql.SQL("ALTER ROLE {} LOGIN CONNECTION LIMIT 1").format(sql.Identifier(desired.owner_role)),
        sql.SQL("ALTER ROLE {} SET statement_timeout = 0").format(sql.Identifier(desired.app_role)),
        sql.SQL("SET ROLE {}").format(sql.Identifier(desired.owner_role)),
        sql.SQL("DROP DATABASE {}").format(sql.Identifier(desired.database_name)),
        "RESET ROLE",
    )

    outcome = await provisioner().ensure("weather", desired, password, [])

    assert outcome.created
    snapshot = await catalog_snapshot(desired)
    owner = next(role for role in snapshot["roles"] if role[0] == desired.owner_role)
    assert (owner[6], owner[7]) == (False, -1)
    assert snapshot["settings"] == [(0, ["statement_timeout=10s"])]


def leftover_statements(desired, leftover):
    """What a test makes by hand (as plugins_admin) to stand for a leftover."""
    return {
        "an owner role without a marker": sql.SQL("CREATE ROLE {} NOLOGIN").format(
            sql.Identifier(desired.owner_role)
        ),
        "an app role without its owner": sql.SQL("CREATE ROLE {} NOLOGIN").format(
            sql.Identifier(desired.app_role)
        ),
        "a database owned by another role": sql.SQL("CREATE DATABASE {}").format(
            sql.Identifier(desired.database_name)
        ),
    }[leftover]


@pytest.mark.postgres
@pytest.mark.parametrize(
    "leftover",
    [
        "an owner role without a marker",
        "an app role without its owner",
        "a database owned by another role",
        "another installation's marker",
    ],
)
async def test_leftovers_this_installation_did_not_create_are_refused_and_left_alone(
    plugin_databases, log_lines, leftover
):
    desired = plugin_databases()
    if leftover == "another installation's marker":
        await provisioner().ensure("weather", desired, new_app_password(), [])
        attempt = desired.model_copy(update={"installation_id": "f" * 32})
    else:
        await as_admin(desired, leftover_statements(desired, leftover))
        attempt = desired
    before = await catalog_snapshot(desired)

    with pytest.raises(DatabaseProvisioningError) as refused:
        await provisioner().ensure("weather", attempt, new_app_password(), [a_migration()])

    assert refused.value.reason == "conflict"
    message = str(refused.value)
    assert message.startswith("plugins_db already has ")
    assert message.endswith(
        "that this plugin installation did not create, probably left from another EpicStaff "
        "database. Remove them (see the operator guide) or restore the matching EpicStaff "
        "database, then press Restart."
    )
    assert await catalog_snapshot(desired) == before
    assert any(line.startswith("plugins.database.failed plugin=weather reason=conflict detail=") for line in log_lines)


@pytest.mark.postgres
async def test_a_role_cross_wired_to_another_plugin_fails_the_assertions(plugin_databases):
    first, second = plugin_databases(), plugin_databases()
    password = new_app_password()
    await provisioner().ensure("first", first, password, [])
    await provisioner().ensure("second", second, new_app_password(), [])
    await as_admin(
        first,
        sql.SQL("GRANT {} TO {}").format(sql.Identifier(second.job_role), sql.Identifier(first.app_role)),
    )

    with pytest.raises(DatabaseProvisioningError) as refused:
        await provisioner().ensure("first", first, password, [])

    assert refused.value.reason == "assertion"
    assert f"unexpected membership {first.app_role} in {second.job_role}" in str(refused.value)


@pytest.mark.postgres
async def test_the_app_role_gets_no_more_sessions_than_its_connection_limit(plugin_databases):
    desired = plugin_databases(connection_limit=2)
    password = new_app_password()
    await provisioner().ensure("weather", desired, password, [])
    sessions = [await connect_as(desired.app_role, password, desired.database_name) for _ in range(2)]
    try:
        with pytest.raises(psycopg.OperationalError, match="too many connections for role"):
            await connect_as(desired.app_role, password, desired.database_name)
    finally:
        for session in sessions:
            await session.close()


@pytest.mark.postgres
async def test_plugin_roles_reach_their_own_database_only(plugin_databases):
    first, second = plugin_databases(), plugin_databases()
    password = new_app_password()
    await provisioner().ensure("first", first, password, [])
    await provisioner().ensure("second", second, new_app_password(), [])

    for database_name in ("postgres", "template1", second.database_name):
        with pytest.raises(psycopg.OperationalError, match="CONNECT privilege"):
            await connect_as(first.app_role, password, database_name)
    for role in (first.owner_role, first.job_role):
        with pytest.raises(psycopg.OperationalError):
            await connect_as(role, password, first.database_name)
    own = await connect_as(first.app_role, password, first.database_name)
    cursor = await own.execute("SELECT current_setting('statement_timeout')")
    assert await cursor.fetchone() == ("10s",)
    await own.close()


@pytest.mark.postgres
async def test_the_admin_connects_only_to_postgres_and_every_session_requires_scram(plugin_databases):
    desired = plugin_databases()
    spy = ConnectionSpy()

    await provisioner(spy).ensure("weather", desired, new_app_password(), [a_migration()])

    admin_sessions = [parameters for parameters in spy.connections if parameters["user"] == ADMIN]
    other_sessions = [parameters for parameters in spy.connections if parameters["user"] != ADMIN]
    assert admin_sessions and {parameters["dbname"] for parameters in admin_sessions} == {"postgres"}
    assert [(parameters["user"], parameters["dbname"]) for parameters in other_sessions] == [
        (desired.owner_role, desired.database_name)
    ]
    assert all(parameters["options"].startswith("-c search_path=pg_catalog") for parameters in admin_sessions)
    for parameters in spy.connections:
        assert (parameters["require_auth"], parameters["connect_timeout"]) == ("scram-sha-256", 10)


@pytest.mark.postgres
async def test_passwords_reach_the_server_only_as_scram_verifiers(plugin_databases):
    desired = plugin_databases()
    password = new_app_password()
    spy = ConnectionSpy()

    await provisioner(spy).ensure("weather", desired, password, [a_migration()])

    with_password = [statement for statement in spy.statements if " PASSWORD " in statement]
    # The app role's, the owner opened for the run, the owner closed again.
    assert len(with_password) == 3
    for statement in with_password:
        assert " PASSWORD 'SCRAM-SHA-256$4096:" in statement or " PASSWORD NULL " in statement
    assert not [statement for statement in spy.statements if password in statement]


async def serve_cleartext_authentication(received: list[bytes]):
    """A server that asks every client for its password in clear text."""

    async def answer(reader, writer):
        try:
            while True:
                length = int.from_bytes(await reader.readexactly(4), "big")
                body = await reader.readexactly(length - 4)
                # SSLRequest and GSSENCRequest: "not supported", the client goes on in clear.
                if body[:4] in (bytes.fromhex("04d2162f"), bytes.fromhex("04d21630")):
                    writer.write(b"N")
                    await writer.drain()
                    continue
                break
            writer.write(b"R" + (8).to_bytes(4, "big") + (3).to_bytes(4, "big"))
            await writer.drain()
            received.append(await reader.read())
        except asyncio.IncompleteReadError:
            pass
        finally:
            writer.close()

    return await asyncio.start_server(answer, "127.0.0.1", 0)


async def test_a_server_asking_for_a_clear_text_password_is_refused_before_it_gets_one():
    received: list[bytes] = []
    server = await serve_cleartext_authentication(received)
    port = server.sockets[0].getsockname()[1]
    password = "p" * 64
    connector = DatabaseConnector(password)
    try:
        with pytest.raises(DatabaseUnreachableError, match="cleartext"):
            async with connector.admin_session(
                DesiredDatabaseServer(name="plugins_db", host="127.0.0.1", port=port)
            ):
                pass
    finally:
        server.close()
        await server.wait_closed()

    assert not [data for data in received if password.encode() in data or data.startswith(b"p")]


async def test_a_server_that_does_not_answer_is_reported_unreachable_without_the_password(log_lines):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    password = "p" * 64
    names = database_names_for("weather")
    desired = DesiredDatabase(
        server=DesiredDatabaseServer(name="plugins_db", host="127.0.0.1", port=port),
        installation_id="a" * 32,
        database_name=names.database,
        owner_role=names.owner_role,
        app_role=names.app_role,
        job_role=names.job_role,
        connection_limit=3,
        statement_timeout_seconds=10,
    )

    with pytest.raises(DatabaseUnreachableError) as unreachable:
        await DatabaseProvisioner(DatabaseConnector(password)).ensure("weather", desired, "a" * 43, [])

    assert str(unreachable.value).startswith(f"plugins_db at 127.0.0.1:{port} cannot be reached: ")
    assert [line for line in log_lines if line.startswith("plugins.database.failed plugin=weather reason=unreachable ")]
    assert not [line for line in log_lines if password in line or "a" * 43 in line]
