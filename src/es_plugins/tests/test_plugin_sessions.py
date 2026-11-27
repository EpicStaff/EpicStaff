"""Ending the database sessions of a plugin whose processes were killed. The tests marked
`postgres` run on a real plugins_db; the others need no server."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from src.shared.models.plugin_nodes import DesiredDatabase, DesiredDatabaseServer, database_names_for

from es_plugins.database.connections import DatabaseConnector
from es_plugins.database.migration_runner import close_owner_login, open_owner_login
from es_plugins.database.placement_database import PlacementDatabase
from es_plugins.database.plugin_sessions import PluginDatabaseSessions
from es_plugins.database.provisioner import DatabaseProvisioner
from tests.helpers import free_port
from tests.plugin_databases import ConnectionSpy, admin_password, connect_as, new_app_password


def unreachable_database() -> DesiredDatabase:
    names = database_names_for("weather")
    return DesiredDatabase(
        server=DesiredDatabaseServer(name="plugins_db", host="127.0.0.1", port=free_port()),
        installation_id=uuid.uuid4().hex,
        database_name=names.database,
        owner_role=names.owner_role,
        app_role=names.app_role,
        job_role=names.job_role,
        connection_limit=3,
        statement_timeout_seconds=10,
    )


async def test_an_unreachable_plugins_db_is_logged_and_never_raised():
    sessions = PluginDatabaseSessions(DatabaseConnector("a" * 64))

    await sessions.end_after_kill(PlacementDatabase("weather", unreachable_database()))


async def test_a_database_being_removed_is_left_to_its_drop():
    spy = ConnectionSpy()
    database = PlacementDatabase("weather", unreachable_database())
    database.retire()

    await PluginDatabaseSessions(DatabaseConnector("a" * 64, connect=spy)).end_after_kill(database)

    assert spy.connections == []


async def provisioned(desired: DesiredDatabase) -> tuple[PlacementDatabase, str]:
    app_password = new_app_password()
    outcome = await DatabaseProvisioner(DatabaseConnector(admin_password())).ensure(
        "weather", desired, app_password, ()
    )
    database = PlacementDatabase("weather", desired)
    database.provisioned(outcome)
    return database, app_password


async def owner_left_logged_in(desired: DesiredDatabase) -> psycopg.AsyncConnection:
    """An owner session a migration could leave: the owner given a password of its own."""
    password = new_app_password()
    async with DatabaseConnector(admin_password()).admin_session(desired.server) as admin:
        await open_owner_login(admin, desired.owner_role, password, datetime.now(UTC) + timedelta(minutes=5))
    return await connect_as(desired.owner_role, password, desired.database_name)


async def ended(session: psycopg.AsyncConnection) -> bool:
    try:
        await session.execute("SELECT 1")
    except psycopg.OperationalError:
        return True
    return False


@pytest.mark.postgres
async def test_a_statement_of_the_killed_plugin_and_an_owner_session_it_opened_are_ended(plugin_databases):
    desired = plugin_databases()
    database, app_password = await provisioned(desired)
    app = await connect_as(desired.app_role, app_password, desired.database_name, options="-c statement_timeout=0")
    # A statement the plugin's dead process left running, with its timeout raised.
    statement = asyncio.create_task(app.execute("SELECT pg_catalog.pg_sleep(60)"))
    await asyncio.sleep(0.5)
    owner = await owner_left_logged_in(desired)
    try:
        await PluginDatabaseSessions(DatabaseConnector(admin_password())).end_after_kill(database)

        with pytest.raises(psycopg.OperationalError):
            await asyncio.wait_for(statement, 10)
        assert await ended(owner)
    finally:
        statement.cancel()
        await app.close()
        await owner.close()
        async with DatabaseConnector(admin_password()).admin_session(desired.server) as admin:
            await close_owner_login(admin, desired.owner_role)


@pytest.mark.postgres
async def test_a_lock_another_task_is_next_for_is_not_waited_for_and_the_app_sessions_still_end(plugin_databases):
    desired = plugin_databases()
    database, app_password = await provisioned(desired)
    app = await connect_as(desired.app_role, app_password, desired.database_name)
    owner = await owner_left_logged_in(desired)
    release_the_waiter = asyncio.Event()

    async def provisioning():
        async with database.lock:
            await release_the_waiter.wait()

    await database.lock.acquire()
    waiter = asyncio.create_task(provisioning())
    await asyncio.sleep(0)
    # Free, but already the waiting task's: taking it would mean waiting for that task's whole run.
    database.lock.release()
    loop = asyncio.get_running_loop()
    try:
        started = loop.time()
        await PluginDatabaseSessions(DatabaseConnector(admin_password())).end_after_kill(database)
        took = loop.time() - started

        assert await ended(app)
        assert not await ended(owner)
        assert took < 2
    finally:
        release_the_waiter.set()
        await waiter
        await app.close()
        await owner.close()
        async with DatabaseConnector(admin_password()).admin_session(desired.server) as admin:
            await close_owner_login(admin, desired.owner_role)


@pytest.mark.postgres
async def test_while_a_node_run_holds_the_database_its_owner_session_is_kept(plugin_databases):
    desired = plugin_databases()
    database, app_password = await provisioned(desired)
    app = await connect_as(desired.app_role, app_password, desired.database_name)
    owner = await owner_left_logged_in(desired)
    try:
        async with database.lock:
            await PluginDatabaseSessions(DatabaseConnector(admin_password())).end_after_kill(database)

        assert await ended(app)
        assert not await ended(owner)
    finally:
        await app.close()
        await owner.close()
        async with DatabaseConnector(admin_password()).admin_session(desired.server) as admin:
            await close_owner_login(admin, desired.owner_role)
