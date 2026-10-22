"""The local database of `epicstaff-plugin dev`: its role check and the migrations applied to it.

Most tests run against a fake connection (`fake_postgres`). The `postgres` ones run the same code
against a real PostgreSQL (`src/plugins_db/lab/run.sh` starts one), with the Weather sample's
migrations and the SDK's transaction helpers, and are skipped without it.
"""

import asyncio
import hashlib
import os
import secrets
import sys
from contextlib import contextmanager

import psycopg
import pytest
from psycopg import sql

from conftest import WEATHER_SAMPLE
from epicstaff_plugin.cli import development_database
from epicstaff_plugin.cli.development_database import (
    DatabaseRoles,
    DatabaseUrl,
    DevelopmentDatabaseError,
    Migration,
    apply_migrations,
    check_roles,
    connect,
    role_setup_sql,
    source_migrations,
)
from epicstaff_plugin.contracts.database import MIGRATION_PLACEHOLDERS
from epicstaff_plugin.database import job_transaction, org_transaction
from epicstaff_plugin.package_source import collect_source
from fake_postgres import FAILING_STATEMENT, FakeConnection

ROLES = DatabaseRoles(login_role="weather_app", job_role="weather_job")
WEATHER_ROLE_SQL = (
    "CREATE ROLE weather_job NOLOGIN;\n"
    "CREATE ROLE weather_app LOGIN PASSWORD '<password>';\n"
    "GRANT weather_job TO weather_app WITH INHERIT FALSE, SET TRUE;\n"
    "CREATE DATABASE weather_development OWNER weather_app;"
)


def _migration(name, text):
    content = text.encode("utf-8") if isinstance(text, str) else text
    return Migration(name=name, sha256=hashlib.sha256(content).hexdigest(), content=content)


def _refusal(connection, plugin_identifier="weather"):
    with pytest.raises(DevelopmentDatabaseError) as raised:
        check_roles(connection, plugin_identifier)
    return str(raised.value)


# The role check.


def test_suitable_roles_pass_and_name_the_job_role():
    connection = FakeConnection()

    assert check_roles(connection, "weather") == ROLES
    assert connection.queried_job_roles == ["weather_job"]


@pytest.mark.parametrize(
    "login_role",
    [("postgres", True, False), ("weather_app", False, True)],
    ids=["superuser", "bypasses row-level security"],
)
def test_a_login_role_above_row_level_security_is_refused_with_the_sql_that_makes_suitable_roles(login_role):
    message = _refusal(FakeConnection(login_role=login_role))

    assert "row-level security would not apply as on EpicStaff" in message
    assert message.endswith(WEATHER_ROLE_SQL)


def test_a_login_role_not_named_like_an_app_role_is_refused():
    message = _refusal(FakeConnection(login_role=("weather_dev", False, False)))

    assert "log in as a role named <name>_app, not weather_dev" in message
    assert message.endswith(WEATHER_ROLE_SQL)


def test_the_suggested_roles_follow_the_login_role_or_else_the_plugin():
    assert _refusal(FakeConnection(login_role=("forecast_app", True, False))).endswith(role_setup_sql("forecast"))
    assert "CREATE ROLE weather_pro_app LOGIN" in _refusal(
        FakeConnection(login_role=("postgres", True, False)), "weather-pro"
    )


def test_a_name_that_needs_quoting_is_quoted_in_the_suggested_sql():
    assert role_setup_sql("Weather").splitlines()[0] == 'CREATE ROLE "Weather_job" NOLOGIN;'


@pytest.mark.parametrize(
    ("job_role", "expected"),
    [
        (None, "the job role weather_job does not exist"),
        ((True, False, True, False), "weather_job is a superuser or bypasses row-level security"),
        ((False, True, True, False), "weather_job is a superuser or bypasses row-level security"),
        ((False, False, False, False), "weather_app may not switch to weather_job"),
        ((False, False, True, True), "weather_app inherits weather_job, so the job role's policies would apply"),
    ],
    ids=["missing", "superuser", "bypasses row-level security", "cannot switch", "inherits"],
)
def test_a_job_role_that_differs_from_the_nodes_is_refused(job_role, expected):
    message = _refusal(FakeConnection(job_role=job_role))

    assert expected in message
    assert message.endswith(WEATHER_ROLE_SQL)


def test_a_server_older_than_postgresql_16_is_refused():
    message = _refusal(FakeConnection(server_version=150012))

    assert message == "the database runs PostgreSQL 15; a development database needs PostgreSQL 16 or later"


def test_every_placeholder_a_migration_may_use_has_a_role():
    replacements = ROLES.placeholder_replacements()

    assert replacements == {
        "${owner_role}": '"weather_app"',
        "${app_role}": '"weather_app"',
        "${job_role}": '"weather_job"',
    }
    assert set(replacements) == {"${" + name + "}" for name in MIGRATION_PLACEHOLDERS}


# Applying migrations.


def test_migrations_apply_in_name_order_each_with_its_ledger_row_and_the_roles_in_place():
    connection = FakeConnection()
    migrations = [
        _migration("002_grants.sql", "GRANT SELECT ON weather.places TO ${job_role};\n"),
        _migration("001_tables.sql", "﻿CREATE TABLE weather.places ();\nALTER TABLE weather.places OWNER TO ${owner_role};\nGRANT ALL ON weather.places TO ${app_role};\n"),
    ]

    run = apply_migrations(connection, ROLES, migrations)

    assert connection.ledger_created
    assert run.applied == ("001_tables.sql", "002_grants.sql")
    assert run.already_applied == 0
    assert connection.committed_migrations == [
        'CREATE TABLE weather.places ();\nALTER TABLE weather.places OWNER TO "weather_app";\nGRANT ALL ON weather.places TO "weather_app";\n',
        'GRANT SELECT ON weather.places TO "weather_job";\n',
    ]
    assert connection.ledger == {migration.name: migration.sha256 for migration in migrations}


def test_an_unchanged_applied_migration_is_skipped():
    connection = FakeConnection()
    migrations = [_migration("001_tables.sql", "CREATE TABLE t ();\n")]
    apply_migrations(connection, ROLES, migrations)

    run = apply_migrations(connection, ROLES, [*migrations, _migration("002_more.sql", "CREATE TABLE u ();\n")])

    assert (run.applied, run.already_applied) == (("002_more.sql",), 1)
    assert len(connection.committed_migrations) == 2


def test_a_migration_changed_after_it_was_applied_is_refused_by_name_and_nothing_runs():
    connection = FakeConnection()
    apply_migrations(connection, ROLES, [_migration("001_tables.sql", "CREATE TABLE t ();\n")])

    with pytest.raises(DevelopmentDatabaseError, match="^001_tables.sql changed after it was applied"):
        apply_migrations(
            connection,
            ROLES,
            [_migration("001_tables.sql", "CREATE TABLE t (id int);\n"), _migration("002_more.sql", "SELECT 1;\n")],
        )
    assert len(connection.committed_migrations) == 1
    assert "002_more.sql" not in connection.ledger


def test_a_failing_migration_rolls_back_alone_names_its_line_and_stops_the_run():
    connection = FakeConnection(failure_message="bo\nom\x1b[31m")
    migrations = [
        _migration("001_tables.sql", "CREATE TABLE t ();\n"),
        _migration("002_broken.sql", f"CREATE TABLE u ();\n\nDO $$ BEGIN {FAILING_STATEMENT}; END $$;\n"),
        _migration("003_later.sql", "CREATE TABLE v ();\n"),
    ]

    with pytest.raises(DevelopmentDatabaseError) as raised:
        apply_migrations(connection, ROLES, migrations)

    # Control characters a migration's message holds never reach the output.
    assert str(raised.value) == "002_broken.sql line 3: [P0001] bo om [31m"
    assert list(connection.ledger) == ["001_tables.sql"]
    assert connection.committed_migrations == ["CREATE TABLE t ();\n"]
    assert connection.info.transaction_status == 0


def test_a_migration_that_ends_its_own_transaction_is_refused_before_its_ledger_row():
    connection = FakeConnection()

    with pytest.raises(DevelopmentDatabaseError, match=r"^001_commits.sql ends its own transaction \(COMMIT or ROLLBACK\)"):
        apply_migrations(connection, ROLES, [_migration("001_commits.sql", "CREATE TABLE t ();\nCOMMIT;\n")])

    assert connection.ledger == {}


def test_a_migration_that_is_not_utf8_is_refused():
    with pytest.raises(DevelopmentDatabaseError, match="^001_latin.sql is not UTF-8 text$"):
        apply_migrations(FakeConnection(), ROLES, [_migration("001_latin.sql", "-- café\n".encode("latin-1"))])


# The source's migrations.


def test_the_source_migrations_are_the_weather_samples_in_name_order(weather_source):
    migrations = source_migrations(collect_source(weather_source, None))

    expected = sorted((WEATHER_SAMPLE / "database" / "migrations").glob("*.sql"))
    assert [migration.name for migration in migrations] == [path.name for path in expected]
    assert [migration.sha256 for migration in migrations] == [hashlib.sha256(path.read_bytes()).hexdigest() for path in expected]


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("database/migrations/notes.txt", "package.database/migrations/notes.txt: is not a migration named database/migrations/NNN_<name>.sql"),
        ("database/seed.sql", "package.database/seed.sql: is not a migration named database/migrations/NNN_<name>.sql"),
        ("database/migrations/001_again.sql", "package.database/migrations/001_weather.sql: has the same number as database/migrations/001_again.sql"),
    ],
    ids=["not sql", "outside migrations", "a number twice"],
)
def test_a_source_the_node_would_refuse_is_refused_before_any_database_work(weather_source, path, expected):
    (weather_source / path).write_text("SELECT 1;\n")

    with pytest.raises(DevelopmentDatabaseError) as raised:
        source_migrations(collect_source(weather_source, None))

    assert expected in str(raised.value).splitlines()


# The database URL and the driver.


def test_a_url_is_shown_with_its_passwords_masked():
    url = DatabaseUrl.parse("postgresql://weather_app:p%40ss@localhost:5432/weather_development?password=other&sslmode=disable")

    assert url.shown == "postgresql://weather_app:***@localhost:5432/weather_development?password=***&sslmode=disable"
    assert url.scrub("failed for p@ss, p%40ss and other") == "failed for ***, *** and ***"
    assert "p@ss" not in repr(url) and "other" not in repr(url)


def test_a_url_without_a_password_is_shown_as_it_is():
    url = DatabaseUrl.parse("postgresql://weather_app@localhost/weather_development")

    assert url.shown == "postgresql://weather_app@localhost/weather_development"
    assert url.scrub("unchanged") == "unchanged"


@pytest.mark.parametrize(
    "value",
    ["mysql://weather_app:hunter2@localhost/db", "postgresql://weather_app:hunter2@localhost:notaport/db", "host=localhost password=hunter2"],
    ids=["another scheme", "bad port", "keyword form"],
)
def test_a_url_that_is_not_postgresql_is_refused_without_repeating_it(value):
    with pytest.raises(ValueError) as raised:
        DatabaseUrl.parse(value)

    assert "hunter2" not in str(raised.value)


def test_a_failed_connection_is_reported_without_the_password(monkeypatch):
    def refuse(conninfo, **settings):
        raise psycopg.OperationalError(f'connection to server failed: password "hunter2" was refused\nfor {conninfo}')

    monkeypatch.setattr(psycopg, "connect", refuse)
    url = DatabaseUrl.parse("postgresql://weather_app:hunter2@localhost/weather_development")

    with pytest.raises(DevelopmentDatabaseError) as raised:
        connect(url)

    message = str(raised.value)
    assert message.startswith("cannot connect to postgresql://weather_app:***@localhost/weather_development:")
    assert "hunter2" not in message
    assert "\n" not in message


def test_without_psycopg_the_database_work_says_what_to_install(monkeypatch):
    monkeypatch.setitem(sys.modules, "psycopg", None)
    url = DatabaseUrl.parse("postgresql://weather_app@localhost/weather_development")

    with pytest.raises(DevelopmentDatabaseError, match="psycopg is not installed in this environment: install the backend's lock"):
        development_database.connect(url)
    with pytest.raises(DevelopmentDatabaseError, match="psycopg is not installed"):
        apply_migrations(FakeConnection(), ROLES, [])


# Against a real PostgreSQL.

HOST = os.environ.get("ES_PLUGINS_TEST_PG_HOST")
PORT = os.environ.get("ES_PLUGINS_TEST_PG_PORT", "5432")
ADMIN_PASSWORD = os.environ.get("ES_PLUGINS_TEST_PG_ADMIN_PASSWORD")
needs_postgres = pytest.mark.skipif(
    not (HOST and ADMIN_PASSWORD),
    reason="needs ES_PLUGINS_TEST_PG_HOST, _PORT and _ADMIN_PASSWORD (src/plugins_db/lab/run.sh)",
)


def _admin():
    return psycopg.connect(
        host=HOST, port=PORT, user="plugins_admin", password=ADMIN_PASSWORD, dbname="postgres", autocommit=True
    )


@contextmanager
def _local_database(*, login_suffix="_app", job_grant="WITH INHERIT FALSE, SET TRUE", job=True):
    """A database owned by a login role, as an author sets one up with `role_setup_sql`; dropped
    afterwards."""
    prefix = f"sdkdev{secrets.token_hex(4)}"
    login, job_role, database = prefix + login_suffix, prefix + "_job", f"{prefix}_development"
    password = secrets.token_urlsafe(24)
    with _admin() as admin:
        try:
            if job:
                admin.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(job_role)))
            admin.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(sql.Identifier(login), sql.Literal(password))
            )
            if job:
                admin.execute(
                    sql.SQL("GRANT {} TO {} " + job_grant).format(sql.Identifier(job_role), sql.Identifier(login))
                )
            # So the admin may create the login role's database, and drop it afterwards.
            admin.execute(
                sql.SQL("GRANT {} TO CURRENT_USER WITH INHERIT FALSE, SET TRUE").format(sql.Identifier(login))
            )
            admin.execute(
                sql.SQL("CREATE DATABASE {} OWNER {} TEMPLATE template0").format(
                    sql.Identifier(database), sql.Identifier(login)
                )
            )
            yield DatabaseUrl.parse(f"postgresql://{login}:{password}@{HOST}:{PORT}/{database}")
        finally:
            admin.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(login)))
            admin.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(database)))
            admin.execute("RESET ROLE")
            admin.execute(
                sql.SQL("DROP ROLE IF EXISTS {}, {}").format(sql.Identifier(login), sql.Identifier(job_role))
            )


@contextmanager
def _session(url):
    connection = connect(url)
    try:
        yield connection
    finally:
        connection.close()


@pytest.mark.postgres
@needs_postgres
def test_weather_migrations_apply_under_the_two_roles_and_keep_organizations_apart(weather_source):
    migrations = source_migrations(collect_source(weather_source, None))
    with _local_database() as url:
        with _session(url) as connection:
            roles = check_roles(connection, "weather")
            first = apply_migrations(connection, roles, migrations)
            again = apply_migrations(connection, roles, migrations)

        assert first.applied == tuple(migration.name for migration in migrations)
        assert (again.applied, again.already_applied) == ((), len(migrations))
        # As on EpicStaff: an organization sees only its own rows, and the job role reaches the
        # expired rows of every organization and nothing else.
        assert asyncio.run(_organizations_and_the_job_role(url.value)) == {
            "expired results Acme sees": 1,
            "expired results purged": 2,
            "places left": 2,
        }


async def _organizations_and_the_job_role(url):
    async with await psycopg.AsyncConnection.connect(url) as connection:
        for org_id, place in ((3, "Lisbon"), (5, "Kyiv")):
            async with org_transaction(connection, org_id):
                await connection.execute(
                    "INSERT INTO weather.saved_places (org_id, name, country, latitude, longitude, created_by, position)"
                    " VALUES (%s, %s, 'X', 1, 1, 1, 1)",
                    (org_id, place),
                )
                await connection.execute(
                    "INSERT INTO weather.popup_results VALUES (%s, 1, 's', '{}', now() - interval '1 hour')",
                    (org_id,),
                )
        async with org_transaction(connection, 3):
            acme_sees = await _count(connection, "weather.popup_results")
        async with job_transaction(connection):
            purged = (await connection.execute("DELETE FROM weather.popup_results")).rowcount
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            async with job_transaction(connection):
                await connection.execute("DELETE FROM weather.saved_places")
        places = 0
        for org_id in (3, 5):
            async with org_transaction(connection, org_id):
                places += await _count(connection, "weather.saved_places")
    return {"expired results Acme sees": acme_sees, "expired results purged": purged, "places left": places}


async def _count(connection, table):
    return (await (await connection.execute(f"SELECT count(*) FROM {table}")).fetchone())[0]


@pytest.mark.postgres
@needs_postgres
@pytest.mark.parametrize(
    ("setup", "expected"),
    [
        ({"login_suffix": "_dev"}, "log in as a role named <name>_app"),
        ({"job": False}, "_job does not exist"),
        ({"job_grant": "WITH INHERIT TRUE, SET TRUE"}, "so the job role's policies would apply to every request"),
        ({"job_grant": "WITH INHERIT FALSE, SET FALSE"}, "may not switch to"),
    ],
    ids=["login role not an app role", "no job role", "inherits the job role", "cannot switch"],
)
def test_the_role_check_reads_a_real_servers_roles(setup, expected):
    with _local_database(**setup) as url, _session(url) as connection:
        with pytest.raises(DevelopmentDatabaseError) as raised:
            check_roles(connection, "weather")

    assert expected in str(raised.value)


@pytest.mark.postgres
@needs_postgres
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("CREATE TABLE b ();\nSELEC 2;\n", '002_second.sql line 2: [42601] syntax error at or near "SELEC"'),
        ("CREATE TABLE b ();\nCOMMIT;\n", "002_second.sql ends its own transaction"),
        ("CREATE TABLE b ();\nCOMMIT;\nBEGIN;\nCREATE TABLE c ();\n", "002_second.sql ends its own transaction"),
    ],
    ids=["syntax error", "commit", "commit and begin again"],
)
def test_a_real_migration_failure_stops_the_run_and_keeps_the_earlier_files(text, expected):
    migrations = [_migration("001_first.sql", "CREATE TABLE a ();\n"), _migration("002_second.sql", text)]
    with _local_database() as url, _session(url) as connection:
        roles = check_roles(connection, "weather")
        with pytest.raises(DevelopmentDatabaseError) as raised:
            apply_migrations(connection, roles, migrations)
        ledger = connection.execute("SELECT name FROM _epicstaff.migrations ORDER BY name").fetchall()

    assert str(raised.value).startswith(expected)
    assert ledger == [("001_first.sql",)]
