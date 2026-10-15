"""django_app's Postgres connection pool: built from settings, shared by requests."""

import asyncio
import importlib
import time
from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest
from django.core.handlers.asgi import ASGIHandler
from django.db import DEFAULT_DB_ALIAS, connection, connections

from django_app.settings import database as database_settings
from django_app.settings import env
from rbac.identity.first_setup_mode import FirstSetupMode
from src.shared.envtools import EnvironmentNotFoundError

POOL_VARIABLES = ("DJANGO_DB_POOL_MIN_SIZE", "DJANGO_DB_POOL_MAX_SIZE", "DJANGO_DB_POOL_TIMEOUT")

# Answers anonymously, and reads the database on every call while first setup is open.
DATABASE_BACKED_PATH = "/api/auth/first-setup/"


@pytest.fixture
def reload_database_settings(monkeypatch):
    """Re-run the settings module under a changed env, then restore it."""
    yield lambda: importlib.reload(database_settings).DATABASES["default"]
    # The env must be back before the module runs again.
    monkeypatch.undo()
    importlib.reload(database_settings)


@pytest.mark.parametrize("variable", POOL_VARIABLES)
def test_a_missing_pool_variable_stops_startup(monkeypatch, reload_database_settings, variable):
    monkeypatch.delitem(env._envs, variable, raising=False)

    with pytest.raises(EnvironmentNotFoundError, match=variable):
        reload_database_settings()


async def _get(handler: ASGIHandler, path: str) -> int:
    request_sent = False
    response_messages = []

    async def receive():
        nonlocal request_sent
        if not request_sent:
            request_sent = True
            return {"type": "http.request", "body": b"", "more_body": False}
        # The client stays connected: Django cancels this wait once it has answered.
        await asyncio.Event().wait()

    async def send(message):
        response_messages.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [(b"host", b"testserver")],
        "client": ("127.0.0.1", 50000),
        "server": ("testserver", 80),
    }
    await handler(scope, receive, send)
    return response_messages[0]["status"]


def _connections_in_use(pool) -> int:
    stats = pool.get_stats()
    return stats["pool_size"] - stats["pool_available"]


def _settled_connections_in_use(pool, expected: int) -> int:
    """Connections lent out, once the pool has finished opening the ones it started.

    `pool_size` counts a connection from the moment the pool starts opening it in the
    background, so right after a burst it can run ahead of the connections available.
    """
    deadline = time.monotonic() + 5
    while (in_use := _connections_in_use(pool)) != expected and time.monotonic() < deadline:
        time.sleep(0.05)
    return in_use


@pytest.mark.django_db
def test_concurrent_requests_reuse_pooled_connections_and_return_them(settings):
    # In cli_only mode the endpoint answers without a query, and this test would prove nothing.
    settings.FIRST_SETUP_MODE = FirstSetupMode.OPEN
    pool = connection.pool
    # This test's own connection comes from the same pool.
    connection.ensure_connection()
    assert connection.connection._pool is pool

    request_count = pool.max_size + 5
    stats_before = pool.get_stats()
    in_use_before = _connections_in_use(pool)

    async def send_concurrent_requests():
        # Under ASGI every request runs its queries in a thread of its own.
        handler = ASGIHandler()
        return await asyncio.gather(
            *(_get(handler, DATABASE_BACKED_PATH) for _ in range(request_count))
        )

    # On an event loop of its own, as an ASGI server runs them. async_to_sync would send
    # every request's queries back to one thread, and so through one connection.
    with ThreadPoolExecutor(max_workers=1) as server_thread:
        statuses = server_thread.submit(asyncio.run, send_concurrent_requests()).result()
    stats_after = pool.get_stats()

    assert statuses == [200] * request_count
    borrowed = stats_after.get("requests_num", 0) - stats_before.get("requests_num", 0)
    assert borrowed >= request_count
    opened = stats_after.get("connections_num", 0) - stats_before.get("connections_num", 0)
    assert opened <= pool.max_size < request_count
    # Every request handed its connection back when it finished.
    assert _settled_connections_in_use(pool, in_use_before) == in_use_before


def _backend_pid() -> int:
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_backend_pid()")
        return cursor.fetchone()[0]


@pytest.fixture
def single_connection_pool():
    """Give this test a pool of its own that holds one connection.

    With one connection, the query after it is dropped can only be handed that same
    connection; a larger pool might lend a healthy idle one and prove nothing.
    """
    connection.close()
    pools = type(connections[DEFAULT_DB_ALIAS])._connection_pools
    session_pool = pools.pop(DEFAULT_DB_ALIAS, None)
    database = connection.settings_dict
    session_options = database["OPTIONS"]
    database["OPTIONS"] = {
        **session_options,
        "pool": {**session_options["pool"], "min_size": 1, "max_size": 1},
    }
    yield
    connection.close()
    database["OPTIONS"] = session_options
    test_pool = pools.pop(DEFAULT_DB_ALIAS, None)
    if test_pool is not None:
        test_pool.close()
    if session_pool is not None:
        pools[DEFAULT_DB_ALIAS] = session_pool


# transaction=True: inside a test transaction Django never hands the connection back.
@pytest.mark.django_db(transaction=True)
def test_a_connection_postgres_dropped_while_pooled_is_replaced_before_a_query(
    single_connection_pool,
):
    dropped_pid = _backend_pid()
    # Back to the pool, idle, as between two requests.
    connection.close()
    database = connection.settings_dict

    # As after a Postgres restart or an idle-connection timeout.
    with psycopg.connect(
        host=database["HOST"],
        port=database["PORT"],
        user=database["USER"],
        password=database["PASSWORD"],
        dbname=database["NAME"],
        autocommit=True,
    ) as admin:
        (terminated,) = admin.execute(
            "SELECT pg_terminate_backend(%s, 5000)", [dropped_pid]
        ).fetchone()
    assert terminated is True

    assert _backend_pid() != dropped_pid
