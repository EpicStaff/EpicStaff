"""Migrations from a verified package, applied as the owner on a real plugins_db (marker `postgres`)."""

import hashlib
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
import pytest
from loguru import logger
from psycopg import sql
from src.shared.models.plugin_nodes import (
    MAX_APPLIED_MIGRATIONS,
    LedgerEntry,
    is_reportable_ledger_entry,
)

from es_plugins.database import migration_runner
from es_plugins.database.connections import DatabaseConnector, DatabaseProvisioningError, scram_verifier
from es_plugins.database.migration_runner import Migration, close_owner_login, open_owner_login
from es_plugins.database.provisioner import DatabaseProvisioner
from es_plugins.packages import package_unpacker
from es_plugins.packages.package_unpacker import read_migrations
from es_plugins.packages.package_verifier import PackageVerificationError, verify_package
from tests.helpers import backend_wheels, manifest, package_files, placement, write_package
from tests.plugin_databases import (
    ConnectionSpy,
    admin_password,
    catalog_snapshot,
    connect_as,
    fetch_all,
    new_app_password,
    owner_session,
)

REPOSITORY = Path(__file__).resolve().parents[3]
WEATHER_MIGRATIONS = REPOSITORY / "plugin-samples/weather/database/migrations"
WEATHER_MIGRATION = WEATHER_MIGRATIONS / "001_weather.sql"


def migration(name: str, text: str | bytes) -> Migration:
    content = text if isinstance(text, bytes) else text.encode()
    return Migration(name=name, sha256=hashlib.sha256(content).hexdigest(), content=content)


async def provision(desired, migrations, password=None, *, spy=None):
    connector = DatabaseConnector(admin_password(), **({"connect": spy} if spy else {}))
    return await DatabaseProvisioner(connector).ensure(
        "weather", desired, password or new_app_password(), migrations
    )


async def ledger(desired) -> list[tuple]:
    async with owner_session(desired) as owner:
        return await fetch_all(owner, "SELECT name, sha256 FROM _epicstaff.migrations ORDER BY applied_at, name")


async def tables(desired) -> set[str]:
    async with owner_session(desired) as owner:
        rows = await fetch_all(
            owner, "SELECT tablename FROM pg_tables WHERE schemaname NOT IN ('pg_catalog', 'information_schema', '_epicstaff')"
        )
    return {row[0] for row in rows}


async def owner_is_closed(desired) -> bool:
    roles = (await catalog_snapshot(desired))["roles"]
    owner = next(role for role in roles if role[0] == desired.owner_role)
    return (owner[6], owner[7], owner[8]) == (False, -1, "infinity")


@pytest.mark.postgres
async def test_migrations_run_in_name_order_and_the_ledger_records_each_files_sha256(plugin_databases):
    desired = plugin_databases()
    files = [
        migration("003_third.sql", "INSERT INTO trail VALUES ('third');"),
        migration("001_first.sql", "CREATE TABLE trail (step text);\nINSERT INTO trail VALUES ('first');"),
        migration("002_second.sql", "INSERT INTO trail VALUES ('second');"),
    ]

    outcome = await provision(desired, files)

    assert [entry.name for entry in outcome.ledger] == ["001_first.sql", "002_second.sql", "003_third.sql"]
    assert all(isinstance(entry, LedgerEntry) for entry in outcome.ledger)
    assert outcome.applied == 3
    assert await ledger(desired) == sorted((file.name, file.sha256) for file in files)
    async with owner_session(desired) as owner:
        assert await fetch_all(owner, "SELECT step FROM trail") == [("first",), ("second",), ("third",)]
    assert (await provision(desired, files)).applied == 0
    assert await owner_is_closed(desired)


@pytest.mark.postgres
async def test_placeholders_become_quoted_role_names(plugin_databases):
    desired = plugin_databases()
    spy = ConnectionSpy()
    text = (
        "CREATE SCHEMA shared;\n"
        "GRANT USAGE ON SCHEMA shared TO ${app_role}, ${job_role};\n"
        "COMMENT ON SCHEMA shared IS 'owned by ${owner_role}';"
    )

    await provision(desired, [migration("001_roles.sql", text)], spy=spy)

    sent = next(statement for statement in spy.statements if statement.startswith("CREATE SCHEMA shared"))
    assert f'TO "{desired.app_role}", "{desired.job_role}"' in sent
    assert "${" not in sent
    async with owner_session(desired) as owner:
        privileges = await fetch_all(
            owner,
            "SELECT has_schema_privilege(%s, 'shared', 'USAGE'), has_schema_privilege(%s, 'shared', 'USAGE')",
            (desired.app_role, desired.job_role),
        )
    assert privileges == [(True, True)]


@pytest.mark.postgres
async def test_everything_a_migration_creates_belongs_to_the_owner(plugin_databases):
    desired = plugin_databases()

    await provision(desired, [migration("001_weather.sql", WEATHER_MIGRATION.read_bytes())])

    async with owner_session(desired) as owner:
        foreign = await fetch_all(
            owner,
            "SELECT n.nspname, c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname IN ('weather', '_epicstaff') AND c.relowner <> %s::regrole",
            (desired.owner_role,),
        )
        schema_owners = await fetch_all(
            owner,
            "SELECT nspname, pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname IN ('weather', '_epicstaff') ORDER BY 1",
        )
    assert foreign == []
    assert schema_owners == [("_epicstaff", desired.owner_role), ("weather", desired.owner_role)]


@pytest.mark.postgres
async def test_an_applied_migration_that_changed_is_refused(plugin_databases):
    desired = plugin_databases()
    await provision(desired, [migration("001_places.sql", "CREATE TABLE places (id int);")])

    with pytest.raises(DatabaseProvisioningError) as refused:
        await provision(
            desired,
            [
                migration("001_places.sql", "CREATE TABLE places (id bigint);"),
                migration("002_more.sql", "CREATE TABLE more (id int);"),
            ],
        )

    assert (refused.value.reason, str(refused.value)) == (
        "migration",
        "001_places.sql changed after it was applied",
    )
    assert await tables(desired) == {"places"}
    assert await owner_is_closed(desired)


@pytest.mark.postgres
async def test_a_failing_migration_rolls_back_alone_and_stops_the_run(plugin_databases):
    desired = plugin_databases()
    files = [
        migration("001_first.sql", "CREATE TABLE first (id int);"),
        migration("002_broken.sql", "CREATE TABLE broken (id int);\n\nSELEC 1;\n"),
        migration("003_never.sql", "CREATE TABLE never (id int);"),
    ]

    with pytest.raises(DatabaseProvisioningError) as failed:
        await provision(desired, files)

    assert failed.value.reason == "migration"
    assert str(failed.value) == '002_broken.sql line 3: [42601] syntax error at or near "SELEC"'
    assert await tables(desired) == {"first"}
    assert [name for name, _ in await ledger(desired)] == ["001_first.sql"]
    # The failure carries what the database holds now: EpicStaff decides Cancel from it.
    assert failed.value.ledger == (LedgerEntry(name="001_first.sql", sha256=files[0].sha256),)
    assert await owner_is_closed(desired)


@pytest.mark.postgres
async def test_a_migration_that_is_not_utf8_fails_naming_the_file(plugin_databases):
    desired = plugin_databases()

    with pytest.raises(DatabaseProvisioningError, match=r"^001_latin1\.sql is not UTF-8 text$"):
        await provision(desired, [migration("001_latin1.sql", "SELECT 'café';".encode("latin-1"))])

    assert await owner_is_closed(desired)


def escape_attempts(desired, other) -> dict[str, str]:
    # Plugin role names never need escaping inside double quotes.
    app, other_app, other_job = (
        f'"{name}"' for name in (desired.app_role, other.app_role, other.job_role)
    )
    return {
        # Ends as the owner again, so a runner that only SET ROLE to the owner would commit it.
        "reset role, then create a role": (
            "RESET ROLE; CREATE ROLE escaped_role LOGIN; SET ROLE ${owner_role};"
        ),
        "set role to plugins_admin": "SET ROLE plugins_admin; CREATE ROLE escaped_role;",
        "re-password another plugin's app role": f"ALTER ROLE {other_app} PASSWORD 'taken-over';",
        "join another plugin's job role": f"GRANT {other_job} TO {app};",
        "run a program on the server": "COPY (SELECT 1) TO PROGRAM 'id';",
        "load an untrusted extension": "CREATE EXTENSION dblink;",
    }


@pytest.mark.postgres
@pytest.mark.parametrize(
    "attempt",
    [
        "reset role, then create a role",
        "set role to plugins_admin",
        "re-password another plugin's app role",
        "join another plugin's job role",
        "run a program on the server",
        "load an untrusted extension",
    ],
)
async def test_a_migration_cannot_escape_its_owner_and_leaves_nothing(plugin_databases, attempt):
    desired, other = plugin_databases(), plugin_databases()
    other_password = new_app_password()
    await provision(other, [], other_password)
    await provision(desired, [])
    before = (await catalog_snapshot(desired), await catalog_snapshot(other))
    text = "CREATE TABLE before_the_attempt (id int);\n" + escape_attempts(desired, other)[attempt]

    with pytest.raises(DatabaseProvisioningError) as refused:
        await provision(desired, [migration("001_escape.sql", text)])

    assert refused.value.reason == "migration"
    assert "[42501]" in str(refused.value)
    assert (await catalog_snapshot(desired), await catalog_snapshot(other)) == before
    assert await tables(desired) == set()
    assert await ledger(desired) == []
    async with DatabaseConnector(admin_password()).admin_session(desired.server) as admin:
        assert await fetch_all(admin, "SELECT 1 FROM pg_roles WHERE rolname = 'escaped_role'") == []
    # The other plugin's app role still logs in with its own password only.
    session = await connect_as(other.app_role, other_password, other.database_name)
    await session.close()
    with pytest.raises(psycopg.OperationalError):
        await connect_as(other.app_role, "taken-over", other.database_name)


@pytest.mark.postgres
async def test_a_trusted_extension_can_be_created(plugin_databases):
    desired = plugin_databases()

    outcome = await provision(
        desired, [migration("001_uuids.sql", "CREATE EXTENSION pgcrypto;\nSELECT gen_random_bytes(8);")]
    )

    assert [entry.name for entry in outcome.ledger] == ["001_uuids.sql"]


@pytest.mark.postgres
async def test_the_weather_migration_keeps_each_organizations_rows_to_itself(plugin_databases):
    desired = plugin_databases()
    password = new_app_password()
    await provision(desired, [migration("001_weather.sql", WEATHER_MIGRATION.read_bytes())], password)
    insert = (
        "INSERT INTO weather.saved_places (org_id, name, country, latitude, longitude, created_by) "
        "VALUES (%s, %s, 'Portugal', 38.7, -9.1, 7)"
    )
    app = await connect_as(desired.app_role, password, desired.database_name)
    try:
        for organization_id, name in ((1, "Lisbon"), (2, "Porto")):
            async with app.transaction():
                await app.execute("SELECT pg_catalog.set_config('app.org_id', %s, true)", (str(organization_id),))
                await app.execute(insert, (organization_id, name))

        async with app.transaction():
            await app.execute("SELECT pg_catalog.set_config('app.org_id', '1', true)")
            assert await fetch_all(app, "SELECT org_id, name FROM weather.saved_places") == [(1, "Lisbon")]
        with pytest.raises(psycopg.errors.InsufficientPrivilege, match="row-level security"):
            async with app.transaction():
                await app.execute("SELECT pg_catalog.set_config('app.org_id', '1', true)")
                await app.execute(insert, (2, "Faro"))
        assert await fetch_all(app, "SELECT count(*) FROM weather.saved_places") == [(0,)]
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            await app.execute("CREATE TABLE weather.mine (id int)")
    finally:
        await app.close()


@pytest.mark.postgres
@pytest.mark.skipif(
    not os.environ.get("ES_PLUGINS_TEST_ASG_MIGRATIONS_DIR"),
    reason="ASG's migrations are optional: set ES_PLUGINS_TEST_ASG_MIGRATIONS_DIR",
)
async def test_asgs_migrations_all_apply(plugin_databases):
    # ASG's migrations name its roles literally, so the plugin is "asg".
    desired = plugin_databases("asg")
    directory = Path(os.environ["ES_PLUGINS_TEST_ASG_MIGRATIONS_DIR"])
    files = [migration(path.name, path.read_bytes()) for path in sorted(directory.glob("[0-9][0-9][0-9]_*.sql"))]

    outcome = await provision(desired, files)

    print(f"ASG: {outcome.applied}/{len(files)} migrations applied")
    assert outcome.applied == len(files) == 92
    assert await owner_is_closed(desired)


def verify(path, desired):
    return verify_package(path, desired.plugin_identifier, desired.package, desired.runtime)


def database_package(tmp_path, migrations: dict[str, bytes], version="0.5.0"):
    plugin_manifest = {**manifest(version=version), "database": {}}
    files = package_files(backend_wheels(tmp_path / "wheels"), plugin_manifest)
    files.update({f"database/migrations/{name}": content for name, content in migrations.items()})
    path = write_package(tmp_path / f"weather-{version}.esplugin", files, version=version)
    return path, placement(path.read_bytes(), version=version)


def test_migrations_are_read_from_the_verified_package_as_packaged(tmp_path):
    contents = {"002_more.sql": b"SELECT 2;\n", "001_places.sql": b"CREATE TABLE places (id int);\n"}
    path, desired = database_package(tmp_path, contents)

    migrations = read_migrations(path, verify(path, desired))

    assert sorted((item.name, item.content, item.sha256) for item in migrations) == sorted(
        (name, content, hashlib.sha256(content).hexdigest()) for name, content in contents.items()
    )


def test_a_migration_that_differs_from_its_listing_is_refused(tmp_path):
    path, desired = database_package(tmp_path, {"001_places.sql": b"CREATE TABLE places (id int);\n"})
    archive = verify(path, desired)
    # The same package name, rewritten after it was verified.
    database_package(tmp_path, {"001_places.sql": b"DROP TABLE places;\n"})

    with pytest.raises(PackageVerificationError, match="001_places.sql does not match CONTENTS.json"):
        read_migrations(path, archive)


def test_migrations_up_to_the_formats_cap_are_read_and_one_byte_more_is_refused(tmp_path, monkeypatch):
    # The package format's own check runs with its real cap; the node's second look with a small one.
    monkeypatch.setattr(package_unpacker, "MAX_MIGRATIONS_TOTAL_BYTES", 21)
    at_the_cap, desired = database_package(tmp_path / "at", {"001_a.sql": b"SELECT 1;\n", "002_b.sql": b"SELECT 22;\n"})
    over_the_cap, over = database_package(tmp_path / "over", {"001_a.sql": b"SELECT 1;\n", "002_b.sql": b"SELECT 333;\n"})

    assert len(read_migrations(at_the_cap, verify(at_the_cap, desired))) == 2
    with pytest.raises(PackageVerificationError, match="hold 22 bytes, more than 21"):
        read_migrations(over_the_cap, verify(over_the_cap, over))


@pytest.mark.postgres
@pytest.mark.parametrize(
    "text",
    [
        "CREATE TABLE early (id int);\nCOMMIT;",
        "CREATE TABLE early (id int);\nROLLBACK;",
        "CREATE TABLE early (id int);\nCOMMIT;\nBEGIN;\nCREATE TABLE late (id int);",
    ],
)
async def test_a_migration_that_ends_its_own_transaction_is_refused_before_its_ledger_row(plugin_databases, text):
    desired = plugin_databases()

    with pytest.raises(DatabaseProvisioningError) as raised:
        await provision(desired, [migration("001_early.sql", text)])

    assert raised.value.reason == "migration"
    assert "001_early.sql ends its own transaction" in str(raised.value)
    assert await ledger(desired) == []
    assert "late" not in await tables(desired)
    assert await owner_is_closed(desired)


@pytest.mark.postgres
async def test_an_owner_session_opened_with_a_password_a_migration_set_is_ended_at_close(plugin_databases):
    desired = plugin_databases()
    await provision(desired, [])
    connector = DatabaseConnector(admin_password())
    first, second = new_app_password(), new_app_password()
    async with connector.admin_session(desired.server) as admin:
        await open_owner_login(admin, desired.owner_role, first, datetime.now(UTC) + timedelta(minutes=5))
        # What a migration can do while its run lasts: give the owner a password of its own.
        owner = await connect_as(desired.owner_role, first, desired.database_name)
        verifier = scram_verifier(owner, desired.owner_role, second)
        await owner.execute(sql.SQL("ALTER ROLE CURRENT_USER PASSWORD {}").format(sql.Literal(verifier)))
        await owner.close()
        left_open = await connect_as(desired.owner_role, second, desired.database_name)

        await close_owner_login(admin, desired.owner_role)

    with pytest.raises(psycopg.OperationalError):
        await left_open.execute("SELECT 1")
    await left_open.close()
    assert await owner_is_closed(desired)
    with pytest.raises(psycopg.OperationalError):
        await connect_as(desired.owner_role, second, desired.database_name)


@pytest.mark.postgres
@pytest.mark.parametrize(
    "rows",
    [
        "INSERT INTO _epicstaff.migrations (name, sha256) VALUES ('001_' || repeat('a', 300) || '.sql', 'x')",
        "INSERT INTO _epicstaff.migrations (name, sha256) VALUES ('../../etc/passwd', 'x'), ('', 'y')",
        "INSERT INTO _epicstaff.migrations (name, sha256) SELECT '9' || lpad(n::text, 4, '0') || '_x.sql', 'x' "
        "FROM generate_series(1, 1500) AS n",
    ],
)
async def test_ledger_rows_a_migration_wrote_are_read_bounded_and_never_reported(plugin_databases, rows):
    desired = plugin_databases()
    lines = []
    sink = logger.add(lines.append, format="{message}", level="WARNING")
    try:
        outcome = await provision(desired, [migration("001_places.sql", f"CREATE TABLE places (id int);\n{rows};")])
    finally:
        logger.remove(sink)

    assert "001_places.sql" in [entry.name for entry in outcome.ledger]
    assert all(is_reportable_ledger_entry(entry.name, entry.sha256) for entry in outcome.ledger)
    assert len(outcome.ledger) <= MAX_APPLIED_MIGRATIONS
    assert [line for line in lines if line.startswith("plugins.database.ledger_entries_dropped count=")]
    assert not [line for line in lines if "passwd" in line or "aaaa" in line]


@pytest.mark.postgres
async def test_a_ledger_whose_name_column_a_migration_made_an_integer_is_read_without_failing(plugin_databases):
    desired = plugin_databases()
    await provision(desired, [migration("001_places.sql", "CREATE TABLE places (id int);")])
    async with owner_session(desired) as owner:
        await owner.execute("DELETE FROM _epicstaff.migrations")
        await owner.execute("ALTER TABLE _epicstaff.migrations ALTER COLUMN name TYPE int USING 7")
        await owner.execute("INSERT INTO _epicstaff.migrations (name, sha256) VALUES (8, 'x')")

    outcome = await provision(desired, [])

    assert outcome.ledger == ()


def test_a_byte_order_mark_at_the_start_of_a_migration_is_dropped():
    text = migration_runner._migration_text(migration("001_a.sql", "﻿CREATE TABLE a (x int);"), {})

    assert text == "CREATE TABLE a (x int);"


class _LedgerRows:
    """An owner session whose ledger holds exactly `rows`, as `_read_ledger` asks for them."""

    def __init__(self, rows):
        self._rows = rows

    async def execute(self, query, *arguments):
        rows = self._rows

        class Cursor:
            async def fetchall(self):
                return rows

        return Cursor()


@pytest.mark.parametrize(
    "bad_row",
    [
        ("001_" + "a" * 300 + ".sql", "a" * 64),
        ("7", "a" * 64),
        ("../etc/passwd", "a" * 64),
        ("002_more.sql", "NOT-A-DIGEST"),
        ("002_more.sql", None),
        ("002_more.sql", "A" * 64),
    ],
)
async def test_a_ledger_row_a_plugin_wrote_never_reaches_the_report(bad_row):
    rows = [("001_places.sql", "a" * 64), bad_row, ("003_last.sql", "b" * 64)]

    entries = await migration_runner.reportable_ledger(_LedgerRows(rows))

    assert entries == (
        LedgerEntry(name="001_places.sql", sha256="a" * 64),
        LedgerEntry(name="003_last.sql", sha256="b" * 64),
    )


@pytest.mark.postgres
async def test_weathers_migrations_apply_on_a_database_with_rows_and_number_each_organizations_places(
    plugin_databases,
):
    desired = plugin_databases("weather")
    password = new_app_password()
    files = {path.name: path.read_bytes() for path in sorted(WEATHER_MIGRATIONS.glob("*.sql"))}
    first = [migration(name, content) for name, content in files.items() if name < "003"]
    await provision(desired, first, password)
    app = await connect_as(desired.app_role, password, desired.database_name)
    try:
        for organization_id, names in ((1, ("Lisbon", "Porto")), (2, ("Kyiv",))):
            for name in names:
                async with app.transaction():
                    await app.execute("SELECT pg_catalog.set_config('app.org_id', %s, true)", (str(organization_id),))
                    await app.execute(
                        "INSERT INTO weather.saved_places (org_id, name, country, latitude, longitude, created_by) "
                        "VALUES (%s, %s, 'X', 1, 2, 7)",
                        (organization_id, name),
                    )
    finally:
        await app.close()

    outcome = await provision(desired, [migration(name, content) for name, content in files.items()], password)

    assert [entry.name for entry in outcome.ledger] == list(files)
    assert outcome.ledger[-1].sha256 == hashlib.sha256(files["003_place_conditions.sql"]).hexdigest()
    async with owner_session(desired) as owner:
        forced = await fetch_all(
            owner,
            "SELECT relname, relforcerowsecurity FROM pg_class "
            "WHERE relnamespace = 'weather'::regnamespace AND relname IN ('saved_places', 'place_conditions') "
            "ORDER BY relname",
        )
    assert forced == [("place_conditions", True), ("saved_places", True)]
    app = await connect_as(desired.app_role, password, desired.database_name)
    try:
        for organization_id, expected in ((1, [("Lisbon", 1), ("Porto", 2)]), (2, [("Kyiv", 1)])):
            async with app.transaction():
                await app.execute("SELECT pg_catalog.set_config('app.org_id', %s, true)", (str(organization_id),))
                assert await fetch_all(app, "SELECT name, position FROM weather.saved_places ORDER BY position") == expected
    finally:
        await app.close()
