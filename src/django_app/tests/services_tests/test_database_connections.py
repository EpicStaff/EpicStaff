from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.db import close_old_connections, connection

from tables.utils.database_connections import keep_database_connections_open


def _select_one():
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        return cursor.fetchone()[0]


@pytest.fixture
def restore_connection_settings():
    # The settings dict is shared by every connection of this process, so the tests
    # that follow must get Django's defaults back.
    original_settings = {
        key: connection.settings_dict[key]
        for key in ("CONN_MAX_AGE", "CONN_HEALTH_CHECKS")
    }
    yield
    connection.settings_dict.update(original_settings)
    connection.close()


@pytest.fixture
def persistent_connections(restore_connection_settings):
    # Opened before the switch, like the connection a worker may already hold.
    _select_one()
    keep_database_connections_open()


# transaction=True: inside a test transaction Django never closes the connection, so
# close_old_connections() would keep it whatever the settings.
@pytest.mark.django_db(transaction=True)
def test_connection_survives_close_old_connections(persistent_connections):
    _select_one()
    raw_connection = connection.connection

    close_old_connections()
    _select_one()

    assert connection.connection is raw_connection


@pytest.mark.django_db(transaction=True)
def test_dropped_connection_is_replaced_before_the_next_query(persistent_connections):
    _select_one()
    dropped_connection = connection.connection
    # As if Postgres had closed it: without the health check, the next query fails.
    dropped_connection.close()

    close_old_connections()

    assert _select_one() == 1
    assert connection.connection is not dropped_connection


def _connection_settings():
    return {
        "CONN_MAX_AGE": connection.settings_dict["CONN_MAX_AGE"],
        "CONN_HEALTH_CHECKS": connection.settings_dict["CONN_HEALTH_CHECKS"],
    }


@pytest.mark.parametrize(
    "command_name, worker_target",
    [
        (
            "cache_redis",
            "tables.management.commands.cache_redis.GraphMessageStreamConsumer.from_settings",
        ),
        ("listen_redis", "tables.management.commands.listen_redis.RedisPubSub"),
    ],
)
def test_redis_worker_command_runs_on_persistent_connections(
    restore_connection_settings, command_name, worker_target
):
    settings_seen_by_worker = {}

    def run_worker():
        settings_seen_by_worker.update(_connection_settings())

    # The worker itself loops forever; only the settings it starts with matter here.
    with patch(worker_target) as worker_factory:
        worker = worker_factory.return_value
        worker.run.side_effect = run_worker
        worker.listen_for_redis_messages_worker.side_effect = run_worker
        call_command(command_name)

    assert settings_seen_by_worker == {"CONN_MAX_AGE": None, "CONN_HEALTH_CHECKS": True}
