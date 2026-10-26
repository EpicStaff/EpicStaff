"""The limits the platform sets on a plugin's app role, and how to tell when they drifted.

The platform owns the app role's connection limit and every role-level setting of it. A plugin
can change its own role's settings (`ALTER ROLE <app> SET …`, also `IN DATABASE …`), so the
provisioner and the limits watchdog put them back; a plugin sets its own defaults with
`ALTER DATABASE … SET` in a migration instead.

`APP_ROLE_SETTINGS` maps each setting to its value for a desired database. A new database limit
that is an app-role setting is one entry here: applying it and the drift check both read it.
"""

from collections.abc import Callable

import psycopg
from psycopg import sql
from src.shared.models.plugin_nodes import DesiredDatabase

from es_plugins.database.database_attributes import reset_role_settings

APP_ROLE_SETTINGS: dict[str, Callable[[DesiredDatabase], str]] = {
    "statement_timeout": lambda desired: f"{desired.statement_timeout_seconds}s",
}
# The name the connection limit goes by when it is reported as drifted.
CONNECTION_LIMIT = "connection_limit"

_APP_ROLE_SETTING_ROWS = sql.SQL(
    "SELECT s.setdatabase, d.datname, s.setconfig FROM pg_catalog.pg_db_role_setting s "
    "LEFT JOIN pg_catalog.pg_database d ON d.oid = s.setdatabase "
    "WHERE s.setrole = (SELECT oid FROM pg_catalog.pg_roles WHERE rolname = %s)"
)


def app_role_settings(desired: DesiredDatabase) -> dict[str, str]:
    """Every setting the app role carries, with its value: `{"statement_timeout": "10s"}`."""
    return {name: value_for(desired) for name, value_for in APP_ROLE_SETTINGS.items()}


async def drifted_limits(admin: psycopg.AsyncConnection, desired: DesiredDatabase) -> list[str]:
    """The names of the app role's limits that differ from the platform's, sorted.

    A setting stored for one database only (`IN DATABASE`) always counts as drifted, as does a
    setting the platform does not set. An app role that does not exist reports nothing here:
    the assertions report it missing.
    """
    cursor = await admin.execute(
        "SELECT rolconnlimit FROM pg_catalog.pg_roles WHERE rolname = %s", (desired.app_role,)
    )
    role = await cursor.fetchone()
    if role is None:
        return []
    expected = app_role_settings(desired)
    drifted = set()
    if role[0] != desired.connection_limit:
        drifted.add(CONNECTION_LIMIT)
    cursor = await admin.execute(_APP_ROLE_SETTING_ROWS, (desired.app_role,))
    found_role_wide = False
    for database_oid, _, configuration in await cursor.fetchall():
        entries = _settings_of(configuration)
        if database_oid != 0:
            drifted.update(entries)
            continue
        found_role_wide = True
        drifted.update(name for name, value in entries.items() if expected.get(name) != value)
        drifted.update(name for name in expected if name not in entries)
    if not found_role_wide:
        drifted.update(expected)
    return sorted(drifted)


def _settings_of(configuration: list[str] | None) -> dict[str, str]:
    """`setconfig` (`["name=value", …]`) as a mapping."""
    settings = {}
    for entry in configuration or []:
        name, _, value = entry.partition("=")
        settings[name] = value
    return settings


async def apply_app_limits(admin: psycopg.AsyncConnection, desired: DesiredDatabase) -> None:
    """Give the app role exactly the platform's connection limit and settings, in one transaction.

    `RESET ALL` role-wide and in every database the role has settings for, then the settings of
    `APP_ROLE_SETTINGS`.
    """
    app = sql.Identifier(desired.app_role)
    async with admin.transaction():
        await admin.execute(
            sql.SQL("ALTER ROLE {} CONNECTION LIMIT {}").format(
                app, sql.Literal(desired.connection_limit)
            )
        )
        await reset_role_settings(admin, desired.app_role)
        for name, value in app_role_settings(desired).items():
            await admin.execute(
                sql.SQL("ALTER ROLE {} SET {} = {}").format(
                    app, sql.Identifier(name), sql.Literal(value)
                )
            )
