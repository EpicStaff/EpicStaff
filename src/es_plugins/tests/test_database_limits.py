"""The limits watchdog against a real plugins_db (marker `postgres`)."""

import asyncio
import socket
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from loguru import logger
from psycopg import sql
from src.shared.models.plugin_nodes import (
    DesiredDatabase,
    DesiredDatabaseServer,
    LedgerEntry,
    database_names_for,
)

from es_plugins.database.connections import DatabaseConnector, scram_verifier
from es_plugins.database.limits_watchdog import PERMISSIONS_CHANGED, DatabaseLimitsWatchdog
from es_plugins.database.migration_runner import open_owner_login
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
    assert "plugins.database.owner_login_closed plugin=weather sessions_ended=0" in log_lines
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


async def owner_session_with_its_own_password(desired) -> psycopg.AsyncConnection:
    """An owner session opened with a password the owner gave itself, as a migration can."""
    connector = DatabaseConnector(admin_password())
    first, second = new_app_password(), new_app_password()
    async with connector.admin_session(desired.server) as admin:
        await open_owner_login(admin, desired.owner_role, first, datetime.now(UTC) + timedelta(minutes=5))
    owner = await connect_as(desired.owner_role, first, desired.database_name)
    verifier = scram_verifier(owner, desired.owner_role, second)
    await owner.execute(sql.SQL("ALTER ROLE CURRENT_USER PASSWORD {}").format(sql.Literal(verifier)))
    await owner.close()
    return await connect_as(desired.owner_role, second, desired.database_name)


@pytest.mark.postgres
async def test_an_owner_able_to_log_in_loses_the_session_a_migration_opened_for_it(plugin_databases, log_lines):
    desired = plugin_databases()
    placement = await provisioned(desired, new_app_password())
    left_open = await owner_session_with_its_own_password(desired)

    await watchdog([placement]).check_once()

    with pytest.raises(psycopg.OperationalError):
        await left_open.execute("SELECT 1")
    await left_open.close()
    owner = next(role for role in (await catalog_snapshot(desired))["roles"] if role[0] == desired.owner_role)
    assert owner[6] is False
    assert "plugins.database.owner_login_closed plugin=weather sessions_ended=1" in log_lines
    assert placement.failures == []


@pytest.mark.postgres
async def test_an_owner_session_left_after_the_owner_was_closed_is_ended(plugin_databases):
    desired = plugin_databases()
    placement = await provisioned(desired, new_app_password())
    left_open = await owner_session_with_its_own_password(desired)
    # An agent that died between NOLOGIN and ending the owner's sessions leaves this.
    await as_admin(desired, sql.SQL("ALTER ROLE {} NOLOGIN").format(sql.Identifier(desired.owner_role)))

    await watchdog([placement]).check_once()

    with pytest.raises(psycopg.OperationalError):
        await left_open.execute("SELECT 1")
    await left_open.close()
    assert placement.failures == []


def _weather_database() -> PlacementDatabase:
    names = database_names_for("weather")
    desired = DesiredDatabase(
        server=DesiredDatabaseServer(name="plugins_db", host="plugins_db", port=5432),
        installation_id="a" * 32,
        database_name=names.database,
        owner_role=names.owner_role,
        app_role=names.app_role,
        job_role=names.job_role,
        connection_limit=3,
        statement_timeout_seconds=10,
    )
    return PlacementDatabase("weather", desired)


def test_the_ledger_is_unknown_until_it_is_read_and_carries_each_files_digest():
    database = _weather_database()
    assert database.report().ledger is None

    ledger = (LedgerEntry(name="001_places.sql", sha256="a" * 64), LedgerEntry(name="002_more.sql", sha256="b" * 64))
    database.provisioned(ProvisionedDatabase(created=False, ledger=ledger, applied=0, size_bytes=1))

    report = database.report()
    assert report.ledger == list(ledger)
    assert report.applied_migrations == ["001_places.sql", "002_more.sql"]


def test_a_failure_keeps_the_ledger_it_did_not_read_and_takes_the_one_it_did():
    database = _weather_database()
    first = (LedgerEntry(name="001_places.sql", sha256="a" * 64),)
    database.provisioned(ProvisionedDatabase(created=False, ledger=first, applied=1, size_bytes=1))

    database.failed("plugins_db cannot be reached")
    assert database.report().ledger == list(first)

    after = (*first, LedgerEntry(name="002_more.sql", sha256="b" * 64))
    database.failed("003_broken.sql line 1: [22012] division by zero", ledger=after)
    report = database.report()
    assert (report.state, report.ledger) == ("failed", list(after))