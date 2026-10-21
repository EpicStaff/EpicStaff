"""`epicstaff_plugin.database` and the Weather sample's stores against a real PostgreSQL.

The database is set up as the plugin node sets one up, with the sample's own migration:
three roles, the owner owns the database and runs `database/migrations/` as the session user,
and the backend logs in as the app role. Runs with `-m postgres` against a plugins_db server
(`src/plugins_db/lab/run.sh` starts one); skipped without it.
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
from epicstaff_plugin.database import NestedOrgTransactionError, org_transaction
from epicstaff_plugin.runtime import RuntimeConfig
from epicstaff_plugin.serve import build_app
from epicstaff_plugin.testing import write_runtime_file

SAMPLE = REPO_ROOT / "plugin-samples" / "weather"
MIGRATION = SAMPLE / "database" / "migrations" / "001_weather.sql"
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
            text = MIGRATION.read_text(encoding="utf-8")
            for placeholder, role in (("${owner_role}", owner), ("${app_role}", app), ("${job_role}", job)):
                text = text.replace(placeholder, sql.Identifier(role).as_string(connection))
            with connection.transaction():
                connection.execute(text)
        admin.execute(sql.SQL("ALTER ROLE {} NOLOGIN PASSWORD NULL").format(sql.Identifier(owner)))
        yield PluginDatabase(
            url=f"postgresql://{app}:{app_password}@{HOST}:{PORT}/{database}?application_name={prefix}",
            database=database,
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


def test_adding_a_forecast_run_forgets_runs_older_than_the_retention(weather_modules, empty_tables):
    async def scenario():
        database = await weather_modules.database.WeatherDatabase.open()
        runs = weather_modules.forecast_runs.ForecastRuns(database)
        try:
            await runs.add(3, 42, 81, "Paris")
            await runs.add(3, 42, 82, "Oslo")
            async with database.transaction(3) as connection:
                await connection.execute(
                    "UPDATE weather.forecast_runs SET created_at = now() - interval '8 days' WHERE session_id = 81"
                )
            await runs.add(3, 42, 83, "Rome")
            return [await runs.started_by(3, 42, session_id) for session_id in (81, 82, 83)]
        finally:
            await database.close()

    assert asyncio.run(scenario()) == [False, True, True]


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
                left = await _scalar(connection, "SELECT count(*) FROM weather.popup_results")
            return taken, left
        finally:
            await database.close()

    taken, left = asyncio.run(scenario())

    assert taken == [{"code": "ada"}, None, None, None]
    assert left == 0
