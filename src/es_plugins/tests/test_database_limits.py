"""The limits watchdog against a real plugins_db (marker `postgres`)."""

import asyncio
import socket
from datetime import UTC, datetime

import pytest
from loguru import logger
from psycopg import sql
from src.shared.models.plugin_nodes import DesiredDatabase, DesiredDatabaseServer, database_names_for

from es_plugins.database.connections import DatabaseConnector
from es_plugins.database.limits_watchdog import PERMISSIONS_CHANGED, DatabaseLimitsWatchdog
from es_plugins.database.placement_database import PlacementDatabase
from es_plugins.database.provisioner import DatabaseProvisioner, ProvisionedDatabase
from tests.plugin_databases import admin_password, catalog_snapshot, connect_as, new_app_password

NOW = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)


class WatchedPlacement:
    """A controller as the watchdog sees it: the database, and the way to fail the placement."""

    def __init__(self, database: PlacementDatabase):
        self.database = database
        self.failures: list[str] = []

    async def fail_database(self, error: str) -> None:
        self.failures.append(error)
        self.database.failed(error)


@pytest.fixture
def log_lines():
    lines = []
    sink = logger.add(lambda message: lines.append(message.rstrip("\n")), format="{message}", level="DEBUG")
    yield lines
    logger.remove(sink)


async def provisioned(desired, password):
    outcome = await DatabaseProvisioner(DatabaseConnector(admin_password())).ensure(
        "weather", desired, password, []
    )
    database = PlacementDatabase("weather", desired)
    database.provisioned(outcome)
    return WatchedPlacement(database)


def watchdog(placements, changes=None):
    return DatabaseLimitsWatchdog(
        DatabaseConnector(admin_password()),
        lambda: placements,
        on_change=lambda: changes.append("changed") if changes is not None else None,
        clock=lambda: NOW,
    )


async def as_admin(desired, *statements):
    async with DatabaseConnector(admin_password()).admin_session(desired.server) as admin:
        for statement in statements:
            await admin.execute(statement)


@pytest.mark.postgres
async def test_settings_the_app_rewrote_for_itself_are_restored_in_one_pass(plugin_databases, log_lines):
    desired = plugin_databases()
    password = new_app_password()
    placement = await provisioned(desired, password)
    app = await connect_as(desired.app_role, password, desired.database_name)
    await app.execute(sql.SQL("ALTER ROLE {} SET statement_timeout = 0").format(sql.Identifier(desired.app_role)))
    await app.execute(
        sql.SQL("ALTER ROLE {} IN DATABASE {} SET work_mem = '8MB'").format(
            sql.Identifier(desired.app_role), sql.Identifier(desired.database_name)
        )
    )
    await app.close()
    changes = []

    await watchdog([placement], changes).check_once()

    assert (await catalog_snapshot(desired))["settings"] == [(0, ["statement_timeout=10s"])]
    assert placement.database.limits_restored_at == NOW
    assert placement.database.report().limits_restored_at == NOW
    assert changes == ["changed"]
    assert "plugins.database.limits_restored plugin=weather settings=statement_timeout,work_mem" in log_lines
    assert not [line for line in log_lines if "8MB" in line]
    assert placement.failures == []


@pytest.mark.postgres
async def test_an_owner_left_able_to_log_in_is_closed_again(plugin_databases, log_lines):
    desired = plugin_databases()
    placement = await provisioned(desired, new_app_password())
    await as_admin(desired, sql.SQL("ALTER ROLE {} LOGIN").format(sql.Identifier(desired.owner_role)))

    await watchdog([placement]).check_once()

    owner = next(role for role in (await catalog_snapshot(desired))["roles"] if role[0] == desired.owner_role)
    assert owner[6] is False
    assert "plugins.database.owner_login_closed plugin=weather" in log_lines
    assert placement.failures == []
    assert placement.database.limits_restored_at is None


@pytest.mark.postgres
async def test_a_membership_changed_outside_epicstaff_fails_the_placement(plugin_databases, log_lines):
    desired, other = plugin_databases(), plugin_databases()
    placement = await provisioned(desired, new_app_password())
    await provisioned(other, new_app_password())
    await as_admin(
        desired,
        sql.SQL("GRANT {} TO {}").format(sql.Identifier(other.job_role), sql.Identifier(desired.app_role)),
    )

    await watchdog([placement]).check_once()

    [failure] = placement.failures
    assert failure.startswith(PERMISSIONS_CHANGED)
    assert f"unexpected membership {desired.app_role} in {other.job_role}" in failure
    assert placement.database.report().state == "failed"
    assert any(line.startswith("plugins.database.failed plugin=weather reason=assertion detail=") for line in log_lines)


@pytest.mark.postgres
async def test_public_given_connect_again_fails_the_placement(plugin_databases):
    desired = plugin_databases()
    placement = await provisioned(desired, new_app_password())
    await as_admin(
        desired,
        sql.SQL("SET ROLE {}").format(sql.Identifier(desired.owner_role)),
        sql.SQL("GRANT CONNECT ON DATABASE {} TO PUBLIC").format(sql.Identifier(desired.database_name)),
        "RESET ROLE",
    )

    await watchdog([placement]).check_once()

    assert [failure for failure in placement.failures if "PUBLIC can connect" in failure]


@pytest.mark.postgres
async def test_the_size_is_measured(plugin_databases):
    desired = plugin_databases()
    placement = await provisioned(desired, new_app_password())
    placement.database.size_bytes = None

    await watchdog([placement]).check_once()

    assert placement.database.report().size_bytes > 0


@pytest.mark.postgres
async def test_a_database_being_provisioned_is_left_alone(plugin_databases):
    desired = plugin_databases()
    password = new_app_password()
    placement = await provisioned(desired, password)
    app = await connect_as(desired.app_role, password, desired.database_name)
    await app.execute(sql.SQL("ALTER ROLE {} SET statement_timeout = 0").format(sql.Identifier(desired.app_role)))
    await app.close()

    async with placement.database.lock:
        # Bounded: a pass that waited for the lock would never end.
        await asyncio.wait_for(watchdog([placement]).check_once(), timeout=10)

    assert (await catalog_snapshot(desired))["settings"] == [(0, ["statement_timeout=0"])]
    assert placement.database.limits_restored_at is None


async def test_an_unreachable_server_is_logged_once_and_changes_nothing(log_lines):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
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
    database = PlacementDatabase("weather", desired)
    database.provisioned(ProvisionedDatabase(created=False, ledger=(), applied=0, size_bytes=1))
    placement = WatchedPlacement(database)
    watch = DatabaseLimitsWatchdog(DatabaseConnector("p" * 64), lambda: [placement], on_change=lambda: None)

    await watch.check_once()
    await watch.check_once()

    assert len([line for line in log_lines if line.startswith("The limits watchdog cannot reach plugins_db")]) == 1
    assert placement.failures == []
    assert database.ready
