"""`epicstaff_plugin.database` and the Weather sample's stores against a real PostgreSQL.

The database is set up as the plugin node sets one up, with the sample's own migrations:
three roles, the owner owns the database and runs `database/migrations/` as the session user,
the backend logs in as the app role, which may SET ROLE to the job role. Runs with
`-m postgres` against a plugins_db server (`src/plugins_db/lab/run.sh` starts one); skipped
without it.
"""

import asyncio
import importlib
import json
import os
import secrets
from dataclasses import dataclass
from types import SimpleNamespace

import psycopg
import pytest
from psycopg import sql

from asgi_client import send_request
from conftest import REPO_ROOT
from epicstaff_plugin.database import (
    ConnectionInTransactionError,
    NestedOrgTransactionError,
    job_transaction,
    org_transaction,
)
from epicstaff_plugin.runtime import RuntimeConfig
from epicstaff_plugin.serve import build_app
from epicstaff_plugin.testing import HookSigner, write_runtime_file

SAMPLE = REPO_ROOT / "plugin-samples" / "weather"
MIGRATIONS = sorted((SAMPLE / "database" / "migrations").glob("*.sql"))
HOST = os.environ.get("ES_PLUGINS_TEST_PG_HOST")
PORT = os.environ.get("ES_PLUGINS_TEST_PG_PORT", "5432")
ADMIN_PASSWORD = os.environ.get("ES_PLUGINS_TEST_PG_ADMIN_PASSWORD")

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(
        not (HOST and ADMIN_PASSWORD),
        reason="needs ES_PLUGINS_TEST_PG_HOST, _PORT and _ADMIN_PASSWORD (src/plugins_db/lab/run.sh)",
    ),
]

ADA = {"id": 42, "email": "ada@acme.test", "name": "Ada"}
EVE = {"id": 43, "email": "eve@acme.test", "name": "Eve"}
BOB = {"id": 77, "email": "bob@contoso.test", "name": "Bob"}
ACME = {"id": 3, "name": "Acme"}
CONTOSO = {"id": 5, "name": "Contoso"}
LISBON = {"name": "Lisbon", "country": "Portugal", "admin1": "Lisbon", "latitude": 38.71667, "longitude": -9.13333}
KYIV = {"name": "Kyiv", "country": "Ukraine", "admin1": "Kyiv City", "latitude": 50.45466, "longitude": 30.5238}
STATE = "3.k3Jq9_x-Lm2Np4Qr6St8Uv"


@dataclass(frozen=True)
class PluginDatabase:
    url: str
    database: str
    app_role: str
    job_role: str


def _connect(user, password, dbname):
    return psycopg.connect(
        host=HOST, port=PORT, user=user, password=password, dbname=dbname, autocommit=True, connect_timeout=10
    )


@pytest.fixture(scope="module")
def plugin_database():
    """A database for one test plugin, migrated with the Weather migration, dropped afterwards."""
    prefix = f"sdktest{secrets.token_hex(4)}"
    owner, app, job, database = f"{prefix}_owner", f"{prefix}_app", f"{prefix}_job", f"plugin_{prefix}"
    app_password, owner_password = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    admin = _connect("plugins_admin", ADMIN_PASSWORD, "postgres")
    try:
        for role in (owner, job):
            admin.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(role)))
        admin.execute(
            sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(sql.Identifier(app), sql.Literal(app_password))
        )
        # As the node grants it: the app role may SET ROLE to the job role, and inherits nothing.
        admin.execute(sql.SQL("GRANT {} TO {} WITH INHERIT FALSE, SET TRUE").format(sql.Identifier(job), sql.Identifier(app)))
        admin.execute(sql.SQL("GRANT {} TO CURRENT_USER WITH INHERIT FALSE, SET TRUE").format(sql.Identifier(owner)))
        admin.execute(
            sql.SQL("CREATE DATABASE {} OWNER {} TEMPLATE template0 ENCODING 'UTF8'").format(
                sql.Identifier(database), sql.Identifier(owner)
            )
        )
        # The migration runs with the owner as the session user, as on the node.
        admin.execute(
            sql.SQL("ALTER ROLE {} LOGIN PASSWORD {}").format(sql.Identifier(owner), sql.Literal(owner_password))
        )
        with _connect(owner, owner_password, database) as connection:
            for migration in MIGRATIONS:
                text = migration.read_text(encoding="utf-8")
                for placeholder, role in (("${owner_role}", owner), ("${app_role}", app), ("${job_role}", job)):
                    text = text.replace(placeholder, sql.Identifier(role).as_string(connection))
                with connection.transaction():
                    connection.execute(text)
        admin.execute(sql.SQL("ALTER ROLE {} NOLOGIN PASSWORD NULL").format(sql.Identifier(owner)))
        yield PluginDatabase(
            url=f"postgresql://{app}:{app_password}@{HOST}:{PORT}/{database}?application_name={prefix}",
            database=database,
            app_role=app,
            job_role=job,
        )
    finally:
        admin.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(owner)))
        admin.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(database)))
        admin.execute("RESET ROLE")
        admin.execute(sql.SQL("DROP ROLE IF EXISTS {}, {}, {}").format(*(sql.Identifier(role) for role in (app, job, owner))))
        admin.close()


@pytest.fixture
def weather_modules(monkeypatch, plugin_database):
    """The sample's modules, with the environment the node gives a backend with a database."""
    monkeypatch.setenv("DATABASE_URL", plugin_database.url)
    monkeypatch.setenv("EPICSTAFF_PLUGIN_DB_CONNECTIONS", "3")
    monkeypatch.syspath_prepend(str(SAMPLE / "backend" / "src"))
    return SimpleNamespace(
        app=importlib.import_module("weather_plugin.app"),
        database=importlib.import_module("weather_plugin.database"),
        forecast_runs=importlib.import_module("weather_plugin.forecast_runs"),
        popup_relay=importlib.import_module("weather_plugin.popup_relay"),
        organization_data=importlib.import_module("weather_plugin.organization_data"),
        retention=importlib.import_module("weather_plugin.retention"),
    )


@pytest.fixture
def empty_tables(plugin_database, weather_modules):
    yield
    asyncio.run(_empty_tables(weather_modules))


async def _empty_tables(weather_modules):
    database = await weather_modules.database.WeatherDatabase.open()
    try:
        for org_id in (ACME["id"], CONTOSO["id"]):
            async with database.transaction(org_id) as connection:
                await connection.execute("DELETE FROM weather.saved_places")
                await connection.execute("DELETE FROM weather.forecast_runs")
                await connection.execute("DELETE FROM weather.popup_results")
    finally:
        await database.close()


async def _scalar(connection, query, params=()):
    row = await (await connection.execute(query, params)).fetchone()
    return row[0] if isinstance(row, tuple) else next(iter(row.values()))


def test_org_transaction_sets_the_organization_for_one_transaction(plugin_database):
    async def scenario():
        async with await psycopg.AsyncConnection.connect(plugin_database.url) as connection:
            async with org_transaction(connection, 3) as yielded:
                inside = await _scalar(yielded, "SELECT current_setting('app.org_id', true)")
                await yielded.execute(
                    "INSERT INTO weather.saved_places (org_id, name, country, latitude, longitude, created_by)"
                    " VALUES (3, 'Lisbon', 'Portugal', 38.7, -9.1, 42)"
                )
            after = await _scalar(connection, "SELECT current_setting('app.org_id', true)")
            unscoped = await _scalar(connection, "SELECT count(*) FROM weather.saved_places")
            await connection.commit()
            async with org_transaction(connection, 3):
                saved = await _scalar(connection, "SELECT count(*) FROM weather.saved_places")
                await connection.execute("DELETE FROM weather.saved_places")
            return inside, after, unscoped, saved

    inside, after, unscoped, saved = asyncio.run(scenario())

    assert inside == "3"
    assert after in ("", None)
    # Without an organization, row-level security shows nothing.
    assert unscoped == 0
    assert saved == 1


def test_org_transaction_rolls_back_what_a_failed_block_wrote(plugin_database):
    async def scenario():
        async with await psycopg.AsyncConnection.connect(plugin_database.url) as connection:
            with pytest.raises(RuntimeError):
                async with org_transaction(connection, 3):
                    await connection.execute(
                        "INSERT INTO weather.saved_places (org_id, name, country, latitude, longitude, created_by)"
                        " VALUES (3, 'Porto', 'Portugal', 41.1, -8.6, 42)"
                    )
                    raise RuntimeError("the block failed")
            async with org_transaction(connection, 3):
                return await _scalar(connection, "SELECT count(*) FROM weather.saved_places")

    assert asyncio.run(scenario()) == 0


def test_org_transaction_cannot_write_another_organizations_rows(plugin_database):
    async def scenario():
        async with await psycopg.AsyncConnection.connect(plugin_database.url) as connection:
            async with org_transaction(connection, 3):
                await connection.execute(
                    "INSERT INTO weather.saved_places (org_id, name, country, latitude, longitude, created_by)"
                    " VALUES (5, 'Kyiv', 'Ukraine', 50.4, 30.5, 77)"
                )

    with pytest.raises(psycopg.errors.InsufficientPrivilege, match="row-level security"):
        asyncio.run(scenario())


def test_a_nested_org_transaction_for_another_organization_writes_nothing(plugin_database):
    async def scenario():
        async with await psycopg.AsyncConnection.connect(plugin_database.url) as connection, await psycopg.AsyncConnection.connect(
            plugin_database.url
        ) as other:
            async with org_transaction(connection, 3):
                async with org_transaction(connection, 3):
                    inner = await _scalar(connection, "SELECT current_setting('app.org_id', true)")
                with pytest.raises(NestedOrgTransactionError):
                    async with org_transaction(other, 5):
                        await other.execute(
                            "INSERT INTO weather.saved_places (org_id, name, country, latitude, longitude, created_by)"
                            " VALUES (5, 'Kyiv', 'Ukraine', 50.4, 30.5, 77)"
                        )
                still = await _scalar(connection, "SELECT current_setting('app.org_id', true)")
            async with org_transaction(other, 5):
                kept = await _scalar(other, "SELECT count(*) FROM weather.saved_places")
            return inner, still, kept

    assert asyncio.run(scenario()) == ("3", "3", 0)


def test_places_of_one_name_in_one_country_are_kept_apart_by_region(weather_modules, empty_tables):
    places = importlib.import_module("weather_plugin.places")
    springfield = {"name": "Springfield", "country": "United States", "latitude": 39.8, "longitude": -89.64}

    async def scenario():
        database = await weather_modules.database.WeatherDatabase.open()
        saved_places = places.SavedPlaces(database)
        outcomes = []
        try:
            for admin1 in ("Illinois", "Missouri", None, "Illinois", None):
                try:
                    await saved_places.add(3, 42, places.PlaceCandidate(**springfield, admin1=admin1))
                    outcomes.append("saved")
                except places.AlreadySaved:
                    outcomes.append("already_saved")
            return outcomes, [place.admin1 for place in await saved_places.list(3)]
        finally:
            await database.close()

    outcomes, regions = asyncio.run(scenario())

    assert outcomes == ["saved", "saved", "saved", "already_saved", "already_saved"]
    assert regions == [None, "Illinois", "Missouri"]


def _as(signer, method, path, person, org, permissions=("read", "update")):
    return {
        **signer.headers(method, path, mode="user", user=person, org=org, permissions=list(permissions)),
        "content-type": "application/json",
    }


def test_places_are_kept_per_organization_and_survive_a_restart(monkeypatch, tmp_path, signer, weather_modules, empty_tables):
    runtime_file = tmp_path / "runtime.json"
    write_runtime_file(runtime_file, signer=signer)
    monkeypatch.setenv("EPICSTAFF_PLUGIN_RUNTIME_FILE", str(runtime_file))
    raw_app = weather_modules.app.app
    for name in ("places", "forecast_runs", "popup_relay", "place_search"):
        # Restored afterwards: the lifespan below sets these on the module's app.
        monkeypatch.setattr(raw_app.state, name, None, raising=False)
    weather = build_app(raw_app, RuntimeConfig.load(runtime_file))

    async def call(method, path, person, org, body=None, permissions=("read", "update")):
        raw = b"" if body is None else json.dumps(body).encode()
        return await send_request(weather, method, path, _as(signer, method, path, person, org, permissions), raw)

    async def first_run():
        async with raw_app.router.lifespan_context(raw_app):
            added = await call("POST", "/api/places", ADA, ACME, LISBON)
            again = await call("POST", "/api/places", EVE, ACME, LISBON)
            viewer = await call("POST", "/api/places", EVE, ACME, KYIV, permissions=("read",))
            bob_adds = await call("POST", "/api/places", BOB, CONTOSO, KYIV)
            bob_lists = await call("GET", "/api/places", BOB, CONTOSO)
            lisbon_id = added.json()["id"]
            bob_removes = await call("DELETE", f"/api/places/{lisbon_id}", BOB, CONTOSO)
            return added, again, viewer, bob_adds, bob_lists, bob_removes

    async def after_restart():
        async with raw_app.router.lifespan_context(raw_app):
            ada_lists = await call("GET", "/api/places", ADA, ACME)
            removed = await call("DELETE", f"/api/places/{ada_lists.json()['places'][0]['id']}", ADA, ACME)
            ada_lists_again = await call("GET", "/api/places", ADA, ACME)
            return ada_lists, removed, ada_lists_again

    added, again, viewer, bob_adds, bob_lists, bob_removes = asyncio.run(first_run())
    ada_lists, removed, ada_lists_again = asyncio.run(after_restart())

    assert added.status == 201
    assert {key: added.json()[key] for key in ("name", "admin1", "country", "latitude", "longitude")} == LISBON
    assert (again.status, again.json()) == (409, {"code": "already_saved"})
    assert (viewer.status, viewer.json()) == (403, {"code": "forbidden"})
    assert bob_adds.status == 201
    assert [place["name"] for place in bob_lists.json()["places"]] == ["Kyiv"]
    assert (bob_removes.status, bob_removes.json()) == (404, {"code": "not_found"})
    assert ada_lists.json() == {"places": [added.json()]}
    assert removed.status == 204
    assert ada_lists_again.json() == {"places": []}


def test_a_forecast_run_is_found_after_a_restart_for_its_person_only(weather_modules, empty_tables):
    async def scenario():
        database = await weather_modules.database.WeatherDatabase.open()
        await weather_modules.forecast_runs.ForecastRuns(database).add(3, 42, 81, "Paris")
        await database.close()
        database = await weather_modules.database.WeatherDatabase.open()
        runs = weather_modules.forecast_runs.ForecastRuns(database)
        try:
            return [
                await runs.started_by(3, 42, 81),
                await runs.started_by(3, 43, 81),
                await runs.started_by(5, 42, 81),
                await runs.started_by(3, 42, 82),
            ]
        finally:
            await database.close()

    assert asyncio.run(scenario()) == [True, False, False, False]


def test_adding_a_forecast_run_keeps_older_runs_for_the_purge(weather_modules, empty_tables):
    async def scenario():
        database = await weather_modules.database.WeatherDatabase.open()
        runs = weather_modules.forecast_runs.ForecastRuns(database)
        try:
            await runs.add(3, 42, 81, "Paris")
            async with database.transaction(3) as connection:
                await connection.execute(
                    "UPDATE weather.forecast_runs SET created_at = now() - interval '8 days' WHERE session_id = 81"
                )
            await runs.add(3, 42, 82, "Oslo")
            kept = [await runs.started_by(3, 42, session_id) for session_id in (81, 82)]
            await weather_modules.retention.RetentionPurge(database).run_once()
            return kept, [await runs.started_by(3, 42, session_id) for session_id in (81, 82)]
        finally:
            await database.close()

    assert asyncio.run(scenario()) == ([True, True], [False, True])


def test_a_popup_result_is_taken_once_by_its_person_until_it_expires(weather_modules, empty_tables):
    async def scenario():
        database = await weather_modules.database.WeatherDatabase.open()
        relay = weather_modules.popup_relay.PopupRelayStore(database)
        try:
            await relay.put(3, 42, STATE, {"code": "first"})
            await relay.put(3, 42, STATE, {"code": "ada"})
            await relay.put(3, 43, STATE, {"code": "eve"})
            taken = [
                await relay.take(3, 42, STATE),
                await relay.take(3, 42, STATE),
                await relay.take(5, 43, STATE),
            ]
            async with database.transaction(3) as connection:
                await connection.execute(
                    "UPDATE weather.popup_results SET expires_at = now() - interval '1 second'"
                )
            taken.append(await relay.take(3, 43, STATE))
            async with database.transaction(3) as connection:
                left_expired = await _scalar(connection, "SELECT count(*) FROM weather.popup_results")
            await weather_modules.retention.RetentionPurge(database).run_once()
            async with database.transaction(3) as connection:
                left_purged = await _scalar(connection, "SELECT count(*) FROM weather.popup_results")
            return taken, left_expired, left_purged
        finally:
            await database.close()

    taken, left_expired, left_purged = asyncio.run(scenario())

    # Eve's result expired before she took it: it is not handed out, and the purge deletes it.
    assert taken == [{"code": "ada"}, None, None, None]
    assert (left_expired, left_purged) == (1, 0)


# --- A connection with a transaction already open ---


def test_a_savepoint_does_not_end_a_transaction_local_setting(plugin_database):
    # Why org_transaction refuses a connection with a transaction open: on one, it would be a
    # savepoint, and the organization it sets would stay set after the block.
    async def scenario():
        async with await psycopg.AsyncConnection.connect(plugin_database.url) as connection:
            await connection.execute("SELECT 1")
            await connection.execute("SAVEPOINT block")
            await connection.execute("SELECT pg_catalog.set_config('app.org_id', '7', true)")
            await connection.execute("RELEASE SAVEPOINT block")
            leaked = await _scalar(connection, "SELECT current_setting('app.org_id', true)")
            await connection.rollback()
            return leaked

    assert asyncio.run(scenario()) == "7"


def test_org_transaction_refuses_a_connection_with_a_transaction_open_and_nothing_leaks(plugin_database, weather_modules, empty_tables):
    async def scenario():
        await _seed(plugin_database.url, CONTOSO["id"], places=1)
        async with await psycopg.AsyncConnection.connect(plugin_database.url) as connection:
            # psycopg opens a transaction for a query outside a transaction block.
            await connection.execute("SELECT 1")
            with pytest.raises(ConnectionInTransactionError):
                async with org_transaction(connection, CONTOSO["id"]):
                    pass
            setting = await _scalar(connection, "SELECT current_setting('app.org_id', true)")
            visible = await _scalar(connection, "SELECT count(*) FROM weather.saved_places")
            await connection.rollback()
            return setting, visible

    setting, visible = asyncio.run(scenario())

    assert setting in ("", None)
    assert visible == 0


# --- The job role ---


async def _seed(url, org_id, *, places=0, old_runs=0, new_runs=0, expired_popups=0, live_popups=0):
    """Insert rows of one organization; old and expired ones each a second apart."""
    async with await psycopg.AsyncConnection.connect(url) as connection, org_transaction(connection, org_id):
        for number in range(places):
            await connection.execute(
                "INSERT INTO weather.saved_places (org_id, name, country, latitude, longitude, created_by)"
                " VALUES (%s, %s, 'Portugal', 38.7, -9.1, 42)",
                (org_id, f"Place {number}"),
            )
        for number in range(old_runs):
            await connection.execute(
                "INSERT INTO weather.forecast_runs (org_id, user_id, session_id, city, created_at)"
                " VALUES (%s, 42, %s, 'Paris', now() - interval '8 days' - make_interval(secs => %s))",
                (org_id, 1000 + number, number),
            )
        for number in range(new_runs):
            await connection.execute(
                "INSERT INTO weather.forecast_runs (org_id, user_id, session_id, city) VALUES (%s, 42, %s, 'Oslo')",
                (org_id, 2000 + number),
            )
        for number in range(expired_popups):
            await connection.execute(
                "INSERT INTO weather.popup_results (org_id, user_id, state, params, expires_at)"
                " VALUES (%s, 42, %s, '{}', now() - make_interval(secs => %s + 1))",
                (org_id, f"expired-{number}", number),
            )
        for number in range(live_popups):
            await connection.execute(
                "INSERT INTO weather.popup_results (org_id, user_id, state, params, expires_at)"
                " VALUES (%s, 42, %s, '{}', now() + interval '5 minutes')",
                (org_id, f"live-{number}"),
            )


async def _counts(url, org_id):
    """How many rows the organization has in each table, as the app role sees them."""
    async with await psycopg.AsyncConnection.connect(url) as connection, org_transaction(connection, org_id):
        return {
            table: await _scalar(connection, f"SELECT count(*) FROM weather.{table}")
            for table in ("saved_places", "forecast_runs", "popup_results")
        }


def _seed_both(url):
    async def seed():
        for org_id in (ACME["id"], CONTOSO["id"]):
            await _seed(url, org_id, places=1, old_runs=1, new_runs=1, expired_popups=1, live_popups=1)

    asyncio.run(seed())


def test_a_job_transaction_runs_as_the_job_role_with_no_organization(plugin_database):
    async def scenario():
        async with await psycopg.AsyncConnection.connect(plugin_database.url) as connection:
            async with job_transaction(connection):
                row = await (
                    await connection.execute("SELECT current_user, session_user, current_setting('app.org_id', true)")
                ).fetchone()
            after = await _scalar(connection, "SELECT current_user")
            await connection.rollback()
            return row, after

    (current, session, org), after = asyncio.run(scenario())

    assert (current, session) == (plugin_database.job_role, plugin_database.app_role)
    assert org in ("", None)
    assert after == plugin_database.app_role


def test_the_job_role_reads_only_the_timestamps_of_expired_rows(plugin_database, weather_modules, empty_tables):
    _seed_both(plugin_database.url)

    async def scenario():
        async with await psycopg.AsyncConnection.connect(plugin_database.url) as connection:
            async with job_transaction(connection):
                runs = await (await connection.execute("SELECT created_at FROM weather.forecast_runs")).fetchall()
                popups = await (await connection.execute("SELECT expires_at FROM weather.popup_results")).fetchall()
            refused = []
            for query in (
                "SELECT org_id FROM weather.forecast_runs",
                "SELECT params FROM weather.popup_results",
                "SELECT name FROM weather.saved_places",
                "DELETE FROM weather.saved_places",
                "UPDATE weather.forecast_runs SET city = 'Rome'",
                "INSERT INTO weather.popup_results (org_id, user_id, state, params, expires_at) VALUES (3, 42, 's', '{}', now())",
            ):
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    async with job_transaction(connection):
                        await connection.execute(query)
                refused.append(query)
            return len(runs), len(popups), len(refused)

    # One old run and one expired popup result in each of the two organizations.
    assert asyncio.run(scenario()) == (2, 2, 6)


def test_the_job_role_deletes_only_expired_rows_even_with_an_organization_set(plugin_database, weather_modules, empty_tables):
    _seed_both(plugin_database.url)

    async def scenario():
        async with await psycopg.AsyncConnection.connect(plugin_database.url) as connection, job_transaction(connection):
            await connection.execute("SELECT pg_catalog.set_config('app.org_id', '3', true)")
            runs = (await connection.execute("DELETE FROM weather.forecast_runs")).rowcount
            popups = (await connection.execute("DELETE FROM weather.popup_results")).rowcount
        return runs, popups, await _counts(plugin_database.url, ACME["id"]), await _counts(plugin_database.url, CONTOSO["id"])

    runs, popups, acme, contoso = asyncio.run(scenario())

    assert (runs, popups) == (2, 2)
    assert acme == contoso == {"saved_places": 1, "forecast_runs": 1, "popup_results": 1}


def test_the_purge_deletes_expired_rows_of_every_organization_in_batches(plugin_database, weather_modules, empty_tables):
    async def scenario():
        await _seed(plugin_database.url, ACME["id"], old_runs=3, new_runs=1, expired_popups=2, live_popups=1)
        await _seed(plugin_database.url, CONTOSO["id"], old_runs=2, new_runs=1, expired_popups=1, live_popups=1)
        database = await weather_modules.database.WeatherDatabase.open()
        try:
            deleted = await weather_modules.retention.RetentionPurge(database, batch_rows=2).run_once()
            again = await weather_modules.retention.RetentionPurge(database, batch_rows=2).run_once()
        finally:
            await database.close()
        return deleted, again, await _counts(plugin_database.url, ACME["id"]), await _counts(plugin_database.url, CONTOSO["id"])

    deleted, again, acme, contoso = asyncio.run(scenario())

    assert deleted == {"weather.forecast_runs": 5, "weather.popup_results": 3}
    assert again == {"weather.forecast_runs": 0, "weather.popup_results": 0}
    assert acme == contoso == {"saved_places": 0, "forecast_runs": 1, "popup_results": 1}


def test_the_purge_walks_the_timestamp_indexes(plugin_database, weather_modules):
    statements = weather_modules.retention.PURGE_STATEMENTS

    async def scenario():
        plans = {}
        async with await psycopg.AsyncConnection.connect(plugin_database.url) as connection, job_transaction(connection):
            # On tables this small the planner prefers a scan; this shows an index can serve.
            await connection.execute("SET LOCAL enable_seqscan = off")
            for table, statement in statements.items():
                rows = await (await connection.execute("EXPLAIN " + statement.replace("%s", "4999"))).fetchall()
                plans[table] = "\n".join(row[0] for row in rows)
        return plans

    plans = asyncio.run(scenario())

    assert "forecast_runs_created_at" in plans["weather.forecast_runs"]
    assert "popup_results_expires_at" in plans["weather.popup_results"]


def test_the_app_role_still_sees_and_deletes_only_its_organizations_rows(plugin_database, weather_modules, empty_tables):
    _seed_both(plugin_database.url)

    async def scenario():
        async with await psycopg.AsyncConnection.connect(plugin_database.url) as connection, org_transaction(connection, ACME["id"]):
            seen = {
                table: await _scalar(connection, f"SELECT count(DISTINCT org_id) FROM weather.{table}")
                for table in ("saved_places", "forecast_runs", "popup_results")
            }
            deleted = (await connection.execute("DELETE FROM weather.popup_results")).rowcount
        return seen, deleted, await _counts(plugin_database.url, CONTOSO["id"])

    seen, deleted, contoso = asyncio.run(scenario())

    assert seen == {"saved_places": 1, "forecast_runs": 1, "popup_results": 1}
    assert deleted == 2
    assert contoso == {"saved_places": 1, "forecast_runs": 2, "popup_results": 2}


# --- The organization removed hook ---


def test_deleting_an_organizations_data_removes_its_rows_from_every_table_only(plugin_database, weather_modules, empty_tables):
    _seed_both(plugin_database.url)

    async def scenario():
        database = await weather_modules.database.WeatherDatabase.open()
        organization_data = weather_modules.organization_data.OrganizationData(database)
        try:
            first = await organization_data.delete(ACME["id"])
            second = await organization_data.delete(ACME["id"])
        finally:
            await database.close()
        return first, second, await _counts(plugin_database.url, ACME["id"]), await _counts(plugin_database.url, CONTOSO["id"])

    first, second, acme, contoso = asyncio.run(scenario())

    assert (first, second) == (5, 0)
    assert acme == {"saved_places": 0, "forecast_runs": 0, "popup_results": 0}
    assert contoso == {"saved_places": 1, "forecast_runs": 2, "popup_results": 2}


def test_the_org_removed_hook_deletes_through_the_running_app(monkeypatch, tmp_path, signer, weather_modules, empty_tables):
    # As the node calls it: the app's lifespan has opened the database (and started the purge),
    # and the organization has no service account in the runtime file.
    _seed_both(weather_modules.database.database_url())
    runtime_file = tmp_path / "runtime.json"
    write_runtime_file(runtime_file, signer=signer)
    raw_app = weather_modules.app.app
    for name in ("places", "forecast_runs", "popup_relay", "organization_data", "place_search"):
        # Restored afterwards: the lifespan below sets these on the module's app.
        monkeypatch.setattr(raw_app.state, name, None, raising=False)
    weather = build_app(raw_app, RuntimeConfig.load(runtime_file))
    call = HookSigner(signer).call("org_removed", org=ACME, job_id=61)

    async def scenario():
        async with raw_app.router.lifespan_context(raw_app):
            first = await send_request(weather, "POST", call.path, call.headers, call.body)
            second = await send_request(weather, "POST", call.path, call.headers, call.body)
        url = weather_modules.database.database_url()
        return first, second, await _counts(url, ACME["id"]), await _counts(url, CONTOSO["id"])

    first, second, acme, contoso = asyncio.run(scenario())

    assert (first.status, first.json()) == (200, {"status": "done"})
    assert (second.status, second.json()) == (200, {"status": "done"})
    assert acme == {"saved_places": 0, "forecast_runs": 0, "popup_results": 0}
    # The purge the lifespan started may already have deleted Contoso's expired rows.
    assert contoso["saved_places"] == 1
    assert contoso["forecast_runs"] >= 1 and contoso["popup_results"] >= 1
