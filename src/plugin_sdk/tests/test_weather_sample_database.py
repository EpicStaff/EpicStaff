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
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx
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


@dataclass(frozen=True)
class _NewPluginDatabase:
    database: PluginDatabase
    migrate: Callable[[Sequence[Path]], None]
    """Run migration files, each in one transaction, as the owner, as the node does."""
    close_owner: Callable[[], None]


@contextmanager
def _new_plugin_database() -> Iterator[_NewPluginDatabase]:
    """A database for one test plugin, set up as the node sets one up, and dropped afterwards.

    No migration has run. The owner may log in until `close_owner()`, as during the node's
    migration window.
    """
    prefix = f"sdktest{secrets.token_hex(4)}"
    owner, app, job, database = f"{prefix}_owner", f"{prefix}_app", f"{prefix}_job", f"plugin_{prefix}"
    app_password, owner_password = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    admin = _connect("plugins_admin", ADMIN_PASSWORD, "postgres")

    def migrate(migrations):
        with _connect(owner, owner_password, database) as connection:
            for migration in migrations:
                text = migration.read_text(encoding="utf-8")
                for placeholder, role in (("${owner_role}", owner), ("${app_role}", app), ("${job_role}", job)):
                    text = text.replace(placeholder, sql.Identifier(role).as_string(connection))
                with connection.transaction():
                    connection.execute(text)

    def close_owner():
        admin.execute(sql.SQL("ALTER ROLE {} NOLOGIN PASSWORD NULL").format(sql.Identifier(owner)))

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
        # The migrations run with the owner as the session user, as on the node.
        admin.execute(
            sql.SQL("ALTER ROLE {} LOGIN PASSWORD {}").format(sql.Identifier(owner), sql.Literal(owner_password))
        )
        yield _NewPluginDatabase(
            database=PluginDatabase(
                url=f"postgresql://{app}:{app_password}@{HOST}:{PORT}/{database}?application_name={prefix}",
                database=database,
                app_role=app,
                job_role=job,
            ),
            migrate=migrate,
            close_owner=close_owner,
        )
    finally:
        admin.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(owner)))
        admin.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(database)))
        admin.execute("RESET ROLE")
        admin.execute(sql.SQL("DROP ROLE IF EXISTS {}, {}, {}").format(*(sql.Identifier(role) for role in (app, job, owner))))
        admin.close()


@pytest.fixture(scope="module")
def plugin_database():
    """A database for one test plugin, migrated with every Weather migration, dropped afterwards."""
    with _new_plugin_database() as new:
        new.migrate(MIGRATIONS)
        new.close_owner()
        yield new.database


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
        places=importlib.import_module("weather_plugin.places"),
        current_conditions=importlib.import_module("weather_plugin.current_conditions"),
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
                    "INSERT INTO weather.saved_places (org_id, name, country, latitude, longitude, created_by, position)"
                    " VALUES (3, 'Lisbon', 'Portugal', 38.7, -9.1, 42, 1)"
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
                        "INSERT INTO weather.saved_places (org_id, name, country, latitude, longitude, created_by, position)"
                        " VALUES (3, 'Porto', 'Portugal', 41.1, -8.6, 42, 1)"
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
                    "INSERT INTO weather.saved_places (org_id, name, country, latitude, longitude, created_by, position)"
                    " VALUES (5, 'Kyiv', 'Ukraine', 50.4, 30.5, 77, 1)"
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
                            "INSERT INTO weather.saved_places (org_id, name, country, latitude, longitude, created_by, position)"
                            " VALUES (5, 'Kyiv', 'Ukraine', 50.4, 30.5, 77, 1)"
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
    # In the order they were saved.
    assert regions == ["Illinois", "Missouri", None]


def _forecast_api_answers(monkeypatch, weather_modules, handler):
    """Make the app's lifespan look temperatures up with `handler` instead of the network."""
    current_conditions = weather_modules.current_conditions
    monkeypatch.setattr(
        weather_modules.app,
        "CurrentTemperature",
        lambda: current_conditions.CurrentTemperature(transport=httpx.MockTransport(handler)),
    )


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
    for name in ("places", "places_with_conditions", "forecast_runs", "popup_relay", "place_search"):
        # Restored afterwards: the lifespan below sets these on the module's app.
        monkeypatch.setattr(raw_app.state, name, None, raising=False)
    # Every temperature lookup fails, so the places carry none.
    _forecast_api_answers(monkeypatch, weather_modules, lambda request: httpx.Response(503))
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
    """Insert rows of one organization; old and expired ones each a second apart.

    Each place gets a temperature.
    """
    async with await psycopg.AsyncConnection.connect(url) as connection, org_transaction(connection, org_id):
        for number in range(places):
            await connection.execute(
                "WITH place AS ("
                " INSERT INTO weather.saved_places (org_id, name, country, latitude, longitude, created_by, position)"
                " VALUES (%s, %s, 'Portugal', 38.7, -9.1, 42, %s) RETURNING org_id, id)"
                " INSERT INTO weather.place_conditions (org_id, place_id, temperature_c, observed_at)"
                " SELECT org_id, id, 18.5, now() FROM place",
                (org_id, f"Place {number}", number + 1),
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
            for table in ("saved_places", "place_conditions", "forecast_runs", "popup_results")
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
                "SELECT temperature_c FROM weather.place_conditions",
                "DELETE FROM weather.place_conditions",
                "UPDATE weather.forecast_runs SET city = 'Rome'",
                "INSERT INTO weather.popup_results (org_id, user_id, state, params, expires_at) VALUES (3, 42, 's', '{}', now())",
            ):
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    async with job_transaction(connection):
                        await connection.execute(query)
                refused.append(query)
            return len(runs), len(popups), len(refused)

    # One old run and one expired popup result in each of the two organizations.
    assert asyncio.run(scenario()) == (2, 2, 8)


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
    assert acme == contoso == {"saved_places": 1, "place_conditions": 1, "forecast_runs": 1, "popup_results": 1}


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
    assert acme == contoso == {"saved_places": 0, "place_conditions": 0, "forecast_runs": 1, "popup_results": 1}


def test_each_purge_batch_finds_its_rows_along_the_timestamp_index_from_where_the_last_ended(plugin_database, weather_modules):
    indexes = {"weather.forecast_runs": "forecast_runs_created_at", "weather.popup_results": "popup_results_expires_at"}
    after, until = "2026-10-01T00:00:00Z", "2026-10-02T00:00:00Z"

    async def scenario():
        plans = {}
        async with await psycopg.AsyncConnection.connect(plugin_database.url) as connection, job_transaction(connection):
            # On tables this small the planner prefers a scan; this shows an index can serve.
            await connection.execute("SET LOCAL enable_seqscan = off")
            cursor = psycopg.AsyncClientCursor(connection)
            for purge in weather_modules.retention.PURGES:
                for name, statement, params in [
                    ("batch_end", purge.batch_end, {"after": after, "offset": 4999}),
                    ("delete_batch", purge.delete_batch, {"after": after, "until": until}),
                ]:
                    await cursor.execute("EXPLAIN " + statement, params)
                    plans[(purge.table, name)] = "\n".join(row[0] for row in await cursor.fetchall())
        return plans

    plans = asyncio.run(scenario())

    def index_conditions(plan):
        return " ".join(line for line in plan.splitlines() if "Index Cond:" in line)

    for purge in weather_modules.retention.PURGES:
        batch_end, delete_batch = plans[(purge.table, "batch_end")], plans[(purge.table, "delete_batch")]
        assert indexes[purge.table] in batch_end and indexes[purge.table] in delete_batch
        assert f"{purge.column} > '2026-10-01" in index_conditions(batch_end)
        # Both bounds are in the index condition: a batch never reads what earlier batches deleted.
        assert f"{purge.column} > '2026-10-01" in index_conditions(delete_batch)
        assert f"{purge.column} <= '2026-10-02" in index_conditions(delete_batch)
        assert "Seq Scan" not in batch_end and "Seq Scan" not in delete_batch


def test_rows_sharing_the_timestamp_a_batch_ends_at_go_with_that_batch(plugin_database, weather_modules, empty_tables):
    async def scenario():
        async with await psycopg.AsyncConnection.connect(plugin_database.url) as connection, org_transaction(connection, ACME["id"]):
            # Five expired runs: two at one moment, three at another, and one live run.
            for session_id, age in [(1, "9 days"), (2, "9 days"), (3, "8 days"), (4, "8 days"), (5, "8 days")]:
                await connection.execute(
                    "INSERT INTO weather.forecast_runs (org_id, user_id, session_id, city, created_at)"
                    " VALUES (%s, 42, %s, 'Paris', date_trunc('second', now()) - %s::interval)",
                    (ACME["id"], session_id, age),
                )
            await connection.execute(
                "INSERT INTO weather.forecast_runs (org_id, user_id, session_id, city) VALUES (%s, 42, 6, 'Oslo')", (ACME["id"],)
            )
        database = await weather_modules.database.WeatherDatabase.open()
        try:
            deleted = await weather_modules.retention.RetentionPurge(database, batch_rows=1).run_once()
        finally:
            await database.close()
        return deleted, await _counts(plugin_database.url, ACME["id"])

    deleted, acme = asyncio.run(scenario())

    assert deleted == {"weather.forecast_runs": 5, "weather.popup_results": 0}
    assert acme["forecast_runs"] == 1


def test_the_app_role_still_sees_and_deletes_only_its_organizations_rows(plugin_database, weather_modules, empty_tables):
    _seed_both(plugin_database.url)

    async def scenario():
        async with await psycopg.AsyncConnection.connect(plugin_database.url) as connection, org_transaction(connection, ACME["id"]):
            seen = {
                table: await _scalar(connection, f"SELECT count(DISTINCT org_id) FROM weather.{table}")
                for table in ("saved_places", "place_conditions", "forecast_runs", "popup_results")
            }
            deleted = (await connection.execute("DELETE FROM weather.popup_results")).rowcount
        return seen, deleted, await _counts(plugin_database.url, CONTOSO["id"])

    seen, deleted, contoso = asyncio.run(scenario())

    assert seen == {"saved_places": 1, "place_conditions": 1, "forecast_runs": 1, "popup_results": 1}
    assert deleted == 2
    assert contoso == {"saved_places": 1, "place_conditions": 1, "forecast_runs": 2, "popup_results": 2}


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

    assert (first, second) == (6, 0)
    assert acme == {"saved_places": 0, "place_conditions": 0, "forecast_runs": 0, "popup_results": 0}
    assert contoso == {"saved_places": 1, "place_conditions": 1, "forecast_runs": 2, "popup_results": 2}


def test_the_org_removed_hook_deletes_through_the_running_app(monkeypatch, tmp_path, signer, weather_modules, empty_tables):
    # As the node calls it: the app's lifespan has opened the database (and started the purge),
    # and the organization has no service account in the runtime file.
    _seed_both(weather_modules.database.database_url())
    runtime_file = tmp_path / "runtime.json"
    write_runtime_file(runtime_file, signer=signer)
    raw_app = weather_modules.app.app
    for name in ("places", "places_with_conditions", "forecast_runs", "popup_relay", "organization_data", "place_search"):
        # Restored afterwards: the lifespan below sets these on the module's app.
        monkeypatch.setattr(raw_app.state, name, None, raising=False)
    _forecast_api_answers(monkeypatch, weather_modules, lambda request: httpx.Response(503))
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
    assert acme == {"saved_places": 0, "place_conditions": 0, "forecast_runs": 0, "popup_results": 0}
    # The purge the lifespan started may already have deleted Contoso's expired rows.
    assert contoso["saved_places"] == 1
    assert contoso["forecast_runs"] >= 1 and contoso["popup_results"] >= 1


# --- A task that outlives the block it started in ---


def test_a_task_that_outlives_its_block_cannot_set_its_organization_in_another_transaction(plugin_database):
    async def scenario():
        async with await psycopg.AsyncConnection.connect(plugin_database.url) as connection:
            block_ended = asyncio.Event()

            async def child():
                await block_ended.wait()
                with pytest.raises(ConnectionInTransactionError):
                    async with org_transaction(connection, ACME["id"]):
                        pass

            async with org_transaction(connection, ACME["id"]):
                task = asyncio.create_task(child())
            # The pool lends the connection to a request for Contoso.
            async with org_transaction(connection, CONTOSO["id"]):
                block_ended.set()
                await task
                return await _scalar(connection, "SELECT current_setting('app.org_id', true)")

    assert asyncio.run(scenario()) == str(CONTOSO["id"])


# --- Weather 0.7.0: positions and temperatures ---

MIGRATIONS_BEFORE_0_7_0 = [migration for migration in MIGRATIONS if migration.name < "003"]
PLACE_CONDITIONS_MIGRATION = SAMPLE / "database" / "migrations" / "003_place_conditions.sql"


def test_the_upgrade_migration_numbers_each_organizations_places_in_the_order_they_were_saved():
    with _new_plugin_database() as new:
        new.migrate(MIGRATIONS_BEFORE_0_7_0)

        async def seed():
            async with await psycopg.AsyncConnection.connect(new.database.url) as connection:
                for org_id, name, saved_at in [
                    (ACME["id"], "Porto", "2026-10-01 10:00Z"),
                    (ACME["id"], "Lisbon", "2026-10-01 09:00Z"),
                    (ACME["id"], "Faro", "2026-10-01 09:00Z"),
                    (CONTOSO["id"], "Kyiv", "2026-10-01 08:00Z"),
                ]:
                    async with org_transaction(connection, org_id):
                        await connection.execute(
                            "INSERT INTO weather.saved_places (org_id, name, country, latitude, longitude, created_by, created_at)"
                            " VALUES (%s, %s, 'Somewhere', 1, 1, 42, %s)",
                            (org_id, name, saved_at),
                        )

        async def read():
            async with await psycopg.AsyncConnection.connect(new.database.url) as connection:
                positions = {}
                for org_id in (ACME["id"], CONTOSO["id"]):
                    async with org_transaction(connection, org_id):
                        rows = await (await connection.execute("SELECT name, position FROM weather.saved_places ORDER BY position")).fetchall()
                        positions[org_id] = rows
                catalog = await (
                    await connection.execute(
                        "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class"
                        " WHERE relnamespace = 'weather'::regnamespace AND relname IN ('saved_places', 'place_conditions')"
                        " ORDER BY relname"
                    )
                ).fetchall()
                not_null = await _scalar(
                    connection,
                    "SELECT attnotnull FROM pg_attribute WHERE attrelid = 'weather.saved_places'::regclass AND attname = 'position'",
                )
                policies = await (
                    await connection.execute(
                        "SELECT policyname, roles::text[] FROM pg_policies WHERE schemaname = 'weather' AND tablename = 'place_conditions'"
                    )
                ).fetchall()
                await connection.rollback()
                return positions, catalog, not_null, policies

        asyncio.run(seed())
        new.migrate([PLACE_CONDITIONS_MIGRATION])
        new.close_owner()
        positions, catalog, not_null, policies = asyncio.run(read())
        app_role = new.database.app_role

    # Faro and Lisbon were saved at the same time: the one saved first comes first.
    assert positions == {ACME["id"]: [("Lisbon", 1), ("Faro", 2), ("Porto", 3)], CONTOSO["id"]: [("Kyiv", 1)]}
    assert not_null is True
    # FORCE is back on saved_places, and on from the start for place_conditions.
    assert catalog == [("place_conditions", True, True), ("saved_places", True, True)]
    assert policies == [("org_rows", [app_role])]


def test_only_the_app_role_may_use_the_temperatures(plugin_database):
    async def scenario():
        async with await psycopg.AsyncConnection.connect(plugin_database.url) as connection:
            rights = {
                role: {
                    privilege: await _scalar(connection, "SELECT has_table_privilege(%s, 'weather.place_conditions', %s)", (role, privilege))
                    for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER")
                }
                for role in (plugin_database.app_role, plugin_database.job_role)
            }
            await connection.rollback()
            return rights

    rights = asyncio.run(scenario())

    assert rights[plugin_database.app_role] == {
        "SELECT": True, "INSERT": True, "UPDATE": True, "DELETE": True, "TRUNCATE": False, "REFERENCES": False, "TRIGGER": False
    }
    assert not any(rights[plugin_database.job_role].values())


def _candidate(weather_modules, place):
    return weather_modules.places.PlaceCandidate(**place)


def test_a_new_place_goes_after_its_organizations_highest_position(weather_modules, empty_tables):
    porto = {"name": "Porto", "country": "Portugal", "latitude": 41.15, "longitude": -8.61}

    async def scenario():
        database = await weather_modules.database.WeatherDatabase.open()
        saved_places = weather_modules.places.SavedPlaces(database)
        try:
            lisbon = await saved_places.add(ACME["id"], 42, _candidate(weather_modules, LISBON))
            kyiv = await saved_places.add(CONTOSO["id"], 77, _candidate(weather_modules, KYIV))
            await saved_places.add(ACME["id"], 42, _candidate(weather_modules, porto))
            await saved_places.remove(ACME["id"], lisbon.id)
            again = await saved_places.add(ACME["id"], 42, _candidate(weather_modules, LISBON))
            listed = await saved_places.list(ACME["id"])
            return lisbon.position, kyiv.position, again.position, [(place.name, place.position) for place in listed]
        finally:
            await database.close()

    first, contoso_first, after_a_removal, listed = asyncio.run(scenario())

    assert (first, contoso_first, after_a_removal) == (1, 1, 3)
    assert listed == [("Porto", 2), ("Lisbon", 3)]


def test_adds_in_one_organization_take_turns_for_the_next_position(plugin_database, weather_modules, empty_tables):
    porto = {"name": "Porto", "country": "Portugal", "latitude": 41.15, "longitude": -8.61}

    async def scenario():
        database = await weather_modules.database.WeatherDatabase.open()
        saved_places = weather_modules.places.SavedPlaces(database)
        holding, release = asyncio.Event(), asyncio.Event()

        async def add_in_progress():
            # Another request's add: it holds the organization's lock, and wrote position 1.
            async with await psycopg.AsyncConnection.connect(plugin_database.url) as holder, org_transaction(holder, ACME["id"]):
                await holder.execute(weather_modules.places.POSITION_LOCK, (ACME["id"],))
                await holder.execute(
                    "INSERT INTO weather.saved_places (org_id, name, country, latitude, longitude, created_by, position)"
                    " VALUES (%s, 'Faro', 'Portugal', 37.02, -7.93, 42, 1)",
                    (ACME["id"],),
                )
                holding.set()
                await release.wait()

        try:
            holder = asyncio.create_task(add_in_progress())
            await holding.wait()
            adding = asyncio.create_task(saved_places.add(ACME["id"], 42, _candidate(weather_modules, porto)))
            # Another organization does not wait.
            other = await asyncio.wait_for(saved_places.add(CONTOSO["id"], 77, _candidate(weather_modules, KYIV)), 5)
            await asyncio.sleep(0.3)
            waited = not adding.done()
            release.set()
            await holder
            added = await asyncio.wait_for(adding, 5)
            return waited, added.position, other.position
        finally:
            await database.close()

    assert asyncio.run(scenario()) == (True, 2, 1)


def _conditions(weather_modules, temperature_c, observed_at):
    return weather_modules.places.PlaceConditions(temperature_c=temperature_c, observed_at=observed_at)


def test_a_stored_temperature_comes_back_with_its_place_and_a_newer_one_replaces_it(weather_modules, empty_tables):
    first_at = datetime(2026, 10, 21, 9, 0, tzinfo=UTC)
    second_at = first_at + timedelta(minutes=20)

    async def scenario():
        database = await weather_modules.database.WeatherDatabase.open()
        saved_places = weather_modules.places.SavedPlaces(database)
        try:
            lisbon = await saved_places.add(ACME["id"], 42, _candidate(weather_modules, LISBON))
            await saved_places.store_conditions(ACME["id"], {lisbon.id: _conditions(weather_modules, 12.34, first_at)})
            first = (await saved_places.list(ACME["id"]))[0].conditions
            await saved_places.store_conditions(ACME["id"], {lisbon.id: _conditions(weather_modules, -3.0, second_at)})
            second = (await saved_places.list(ACME["id"]))[0].conditions
            async with database.transaction(ACME["id"]) as connection:
                rows = await _scalar(connection, "SELECT count(*) FROM weather.place_conditions")
            return first, second, rows
        finally:
            await database.close()

    first, second, rows = asyncio.run(scenario())

    assert (first.temperature_c, first.observed_at) == (12.3, first_at)
    assert type(first.temperature_c) is float
    assert (second.temperature_c, second.observed_at) == (-3.0, second_at)
    assert rows == 1


def test_storing_a_temperature_skips_a_place_removed_meanwhile(plugin_database, weather_modules, empty_tables):
    async def scenario():
        database = await weather_modules.database.WeatherDatabase.open()
        saved_places = weather_modules.places.SavedPlaces(database)
        try:
            lisbon = await saved_places.add(ACME["id"], 42, _candidate(weather_modules, LISBON))
            async with await psycopg.AsyncConnection.connect(plugin_database.url) as remover:
                async with org_transaction(remover, ACME["id"]):
                    await remover.execute("DELETE FROM weather.saved_places WHERE id = %s", (lisbon.id,))
                    storing = asyncio.create_task(
                        saved_places.store_conditions(ACME["id"], {lisbon.id: _conditions(weather_modules, 12.0, datetime.now(UTC))})
                    )
                    await asyncio.sleep(0.3)
                    waited = not storing.done()
                # The removal committed: the store finishes without an error, and stores nothing.
                await asyncio.wait_for(storing, 5)
            async with database.transaction(ACME["id"]) as connection:
                rows = await _scalar(connection, "SELECT count(*) FROM weather.place_conditions")
            return waited, rows
        finally:
            await database.close()

    assert asyncio.run(scenario()) == (True, 0)


def test_storing_skips_a_place_of_another_organization(weather_modules, empty_tables):
    async def scenario():
        database = await weather_modules.database.WeatherDatabase.open()
        saved_places = weather_modules.places.SavedPlaces(database)
        try:
            kyiv = await saved_places.add(CONTOSO["id"], 77, _candidate(weather_modules, KYIV))
            await saved_places.store_conditions(ACME["id"], {kyiv.id: _conditions(weather_modules, 12.0, datetime.now(UTC))})
            return (await saved_places.list(CONTOSO["id"]))[0].conditions
        finally:
            await database.close()

    assert asyncio.run(scenario()) is None


def test_a_temperature_cannot_name_another_organizations_place(plugin_database, weather_modules, empty_tables):
    async def scenario():
        database = await weather_modules.database.WeatherDatabase.open()
        try:
            kyiv = await weather_modules.places.SavedPlaces(database).add(CONTOSO["id"], 77, _candidate(weather_modules, KYIV))
        finally:
            await database.close()
        async with await psycopg.AsyncConnection.connect(plugin_database.url) as connection, org_transaction(connection, ACME["id"]):
            # Row-level security passes this row: it is Acme's. The foreign key names the
            # organization as well, so it refuses a place that is not Acme's.
            await connection.execute(
                "INSERT INTO weather.place_conditions (org_id, place_id, temperature_c, observed_at) VALUES (%s, %s, 1.0, now())",
                (ACME["id"], kyiv.id),
            )

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        asyncio.run(scenario())


def test_temperatures_are_kept_per_organization(plugin_database, weather_modules, empty_tables):
    async def scenario():
        database = await weather_modules.database.WeatherDatabase.open()
        saved_places = weather_modules.places.SavedPlaces(database)
        now = datetime.now(UTC)
        try:
            lisbon = await saved_places.add(ACME["id"], 42, _candidate(weather_modules, LISBON))
            kyiv = await saved_places.add(CONTOSO["id"], 77, _candidate(weather_modules, KYIV))
            await saved_places.store_conditions(ACME["id"], {lisbon.id: _conditions(weather_modules, 20.0, now)})
            await saved_places.store_conditions(CONTOSO["id"], {kyiv.id: _conditions(weather_modules, 5.0, now)})
            async with database.transaction(ACME["id"]) as connection:
                seen = await (await connection.execute("SELECT org_id, temperature_c FROM weather.place_conditions")).fetchall()
            async with await psycopg.AsyncConnection.connect(plugin_database.url) as connection:
                with pytest.raises(psycopg.errors.InsufficientPrivilege, match="row-level security"):
                    async with org_transaction(connection, ACME["id"]):
                        await connection.execute(
                            "UPDATE weather.place_conditions SET org_id = %s WHERE place_id = %s", (CONTOSO["id"], lisbon.id)
                        )
            return [(row["org_id"], float(row["temperature_c"])) for row in seen]
        finally:
            await database.close()

    assert asyncio.run(scenario()) == [(ACME["id"], 20.0)]


def test_a_places_temperature_goes_with_the_place(weather_modules, empty_tables):
    async def scenario():
        database = await weather_modules.database.WeatherDatabase.open()
        saved_places = weather_modules.places.SavedPlaces(database)
        try:
            lisbon = await saved_places.add(ACME["id"], 42, _candidate(weather_modules, LISBON))
            await saved_places.store_conditions(ACME["id"], {lisbon.id: _conditions(weather_modules, 20.0, datetime.now(UTC))})
            await saved_places.remove(ACME["id"], lisbon.id)
            async with database.transaction(ACME["id"]) as connection:
                return await _scalar(connection, "SELECT count(*) FROM weather.place_conditions")
        finally:
            await database.close()

    assert asyncio.run(scenario()) == 0


def test_the_running_app_lists_temperatures_as_json_numbers_and_utc_times(monkeypatch, tmp_path, signer, plugin_database, weather_modules, empty_tables):
    # A session in another time zone: timestamps come back with that offset, and leave as UTC.
    monkeypatch.setenv("DATABASE_URL", plugin_database.url + "&options=-c%20TimeZone%3DAsia%2FTokyo")
    runtime_file = tmp_path / "runtime.json"
    write_runtime_file(runtime_file, signer=signer)
    raw_app = weather_modules.app.app
    for name in ("places", "places_with_conditions", "forecast_runs", "popup_relay", "place_search"):
        # Restored afterwards: the lifespan below sets these on the module's app.
        monkeypatch.setattr(raw_app.state, name, None, raising=False)
    lookups = []

    def forecast_api(request):
        lookups.append(dict(request.url.params))
        return httpx.Response(200, json={"current": {"time": "2026-10-21T12:15", "temperature_2m": 12.4}})

    _forecast_api_answers(monkeypatch, weather_modules, forecast_api)
    weather = build_app(raw_app, RuntimeConfig.load(runtime_file))

    async def call(method, path, body=None):
        raw = b"" if body is None else json.dumps(body).encode()
        return await send_request(weather, method, path, _as(signer, method, path, ADA, ACME), raw)

    async def scenario():
        async with raw_app.router.lifespan_context(raw_app):
            added = await call("POST", "/api/places", LISBON)
            looked_up = await call("GET", "/api/places")
            # Read back from the database: a Decimal and a Tokyo timestamp.
            stored = await call("GET", "/api/places")
            return added, looked_up, stored

    added, looked_up, stored = asyncio.run(scenario())

    assert (added.status, added.json()["position"], added.json()["conditions"]) == (201, 1, None)
    for response in (looked_up, stored):
        (place,) = response.json()["places"]
        assert b'"temperature_c":12.4,' in response.body
        assert type(place["conditions"]["temperature_c"]) is float
        assert type(place["position"]) is int
        assert place["conditions"]["observed_at"].endswith("Z")
        assert datetime.fromisoformat(place["conditions"]["observed_at"]).utcoffset() == timedelta(0)
    assert stored.json() == looked_up.json()
    assert lookups == [{"latitude": "38.71667", "longitude": "-9.13333", "current": "temperature_2m"}]
