"""Persistent database connections for the long-lived django_app worker processes."""

from django.db import connections


def keep_database_connections_open() -> None:
    """Make this process reuse its database connections instead of reconnecting.

    For ``listen_redis`` and ``cache_redis`` only. They call ``close_old_connections()``
    before handling every message or batch; with Django's default ``CONN_MAX_AGE`` of 0
    that closes the connection each time, so the next query opens a new one (a Postgres
    backend fork and authentication, dozens of times per session). The web server keeps
    the default: Django advises against persistent connections under ASGI.

    With health checks, the first query after ``close_old_connections()`` checks the
    connection and replaces it if Postgres dropped it (a restart, a failover), so the
    message being handled does not fail on a dead connection.

    Must run before the process's first query: Django reads these settings only when it
    opens a connection, so one already open is closed here to reopen with them.
    """
    for connection in connections.all():
        # Every thread's connection shares this dict, so threads started later use it too.
        connection.settings_dict["CONN_MAX_AGE"] = None
        connection.settings_dict["CONN_HEALTH_CHECKS"] = True
        connection.close()
