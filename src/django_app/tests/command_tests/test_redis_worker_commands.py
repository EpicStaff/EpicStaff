"""listen_redis and cache_redis start and query the database under the connection pool."""

import threading
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.db import DEFAULT_DB_ALIAS, connection, connections


@pytest.fixture
def fresh_process_pool():
    """Make the next query build the connection pool, as a newly started process does.

    Django checks its settings, CONN_MAX_AGE among them, only when it builds a pool, and
    the test session has built one already.
    """
    pools = type(connections[DEFAULT_DB_ALIAS])._connection_pools
    session_pool = pools.pop(DEFAULT_DB_ALIAS, None)
    yield
    worker_pool = pools.pop(DEFAULT_DB_ALIAS, None)
    if worker_pool is not None:
        worker_pool.close()
    if session_pool is not None:
        pools[DEFAULT_DB_ALIAS] = session_pool


def _start_worker_command(command_name: str, worker_target: str, worker_entry: str):
    """Run the command in a thread of its own, so it opens its own connection.

    The worker loops on Redis forever; it is replaced by one query, the first a real
    worker runs on every message. Returns what that query got, or what it raised.
    """
    outcome = {}

    def first_query():
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            outcome["result"] = cursor.fetchone()[0]

    def run_command():
        try:
            with patch(worker_target) as worker_factory:
                getattr(worker_factory.return_value, worker_entry).side_effect = first_query
                call_command(command_name)
        except Exception as error:
            outcome["error"] = error
        finally:
            connections.close_all()

    thread = threading.Thread(target=run_command)
    thread.start()
    thread.join(timeout=30)
    assert not thread.is_alive()
    return outcome


@pytest.mark.django_db
@pytest.mark.parametrize(
    "command_name, worker_target, worker_entry",
    [
        (
            "listen_redis",
            "tables.management.commands.listen_redis.RedisPubSub",
            "listen_for_redis_messages_worker",
        ),
        (
            "cache_redis",
            "tables.management.commands.cache_redis.GraphMessageStreamConsumer.from_settings",
            "run",
        ),
    ],
)
def test_redis_worker_queries_through_a_new_pool_at_startup(
    fresh_process_pool, command_name, worker_target, worker_entry
):
    outcome = _start_worker_command(command_name, worker_target, worker_entry)

    assert outcome == {"result": 1}
