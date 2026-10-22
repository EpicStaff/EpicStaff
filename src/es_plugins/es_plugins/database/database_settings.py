"""A plugin database's own settings (`ALTER DATABASE … SET`): read before a backup, set after a restore.

They live in the cluster's catalog (`pg_db_role_setting`), not in the database, so a dump does not
hold them. A backup reads them from `postgres` as `plugins_admin`; a restore sets them again as the
owner (`SET ROLE`, from `postgres`), with each name an identifier and each value a literal.

PostgreSQL stores a list setting such as `search_path` already quoted element by element
(`search_path="app, public"`, `"$user", public`). Set back as one literal it would become a single
element, so those settings are split into their elements first, by the rule pg_dump uses for the
same purpose. Only the database's own entries are kept, not those for one role in it.

A plugin chooses the names and values, so both are bounded, and an entry that does not fit, or
that the server refuses when it is set again, is skipped. Only the number skipped is logged.
"""

import re
from dataclasses import dataclass

import psycopg
from psycopg import sql
from src.shared.models.plugin_nodes import DesiredDatabase

SETTING_NAME_PATTERN = re.compile(r"^[a-z_][a-z0-9_]*(\.[a-z_][a-z0-9_]*)*$")
MAX_DATABASE_SETTINGS = 100
MAX_SETTING_LENGTH = 8192
# The settings PostgreSQL quotes element by element (GUC_LIST_QUOTE), as pg_dump names them.
LIST_QUOTED_SETTINGS = frozenset(
    {
        "local_preload_libraries",
        "search_path",
        "session_preload_libraries",
        "shared_preload_libraries",
        "temp_tablespaces",
        "unix_socket_directories",
    }
)
_DATABASE_SETTINGS = (
    "SELECT pg_catalog.left(entry, %(cut)s) FROM pg_catalog.pg_db_role_setting s, "
    "pg_catalog.unnest(s.setconfig) AS entry "
    "WHERE s.setrole = 0 "
    "AND s.setdatabase = (SELECT oid FROM pg_catalog.pg_database WHERE datname = %(database)s) "
    "LIMIT %(limit)s"
)


@dataclass(frozen=True)
class DatabaseSetting:
    name: str
    value: str
    """As PostgreSQL stores it: list settings are already quoted element by element."""


@dataclass(frozen=True)
class ReadSettings:
    settings: tuple[DatabaseSetting, ...]
    skipped: int
    """Entries left out: too long, a name that is not a setting name, or past the first 100."""


async def read_database_settings(
    admin: psycopg.AsyncConnection, database_name: str
) -> ReadSettings:
    """The database's own settings, read on an admin session to `postgres`."""
    cursor = await admin.execute(
        _DATABASE_SETTINGS,
        {
            "cut": MAX_SETTING_LENGTH + 1,
            "database": database_name,
            "limit": MAX_DATABASE_SETTINGS + 1,
        },
    )
    settings = []
    skipped = 0
    for (entry,) in await cursor.fetchall():
        name, separator, value = entry.partition("=")
        if (
            len(settings) == MAX_DATABASE_SETTINGS
            or not separator
            or len(entry) > MAX_SETTING_LENGTH
            or not SETTING_NAME_PATTERN.fullmatch(name)
        ):
            skipped += 1
            continue
        settings.append(DatabaseSetting(name=name, value=value))
    return ReadSettings(settings=tuple(settings), skipped=skipped)


async def apply_database_settings(
    admin: psycopg.AsyncConnection, desired: DesiredDatabase, settings: tuple[DatabaseSetting, ...]
) -> int:
    """Set each setting on the database again, as its owner; return how many were skipped.

    Each runs in a savepoint of one transaction, so a value the server refuses skips that
    setting alone.
    """
    database = sql.Identifier(desired.database_name)
    skipped = 0
    async with admin.transaction():
        await admin.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(desired.owner_role)))
        for setting in settings:
            statement = setting_statement(database, setting)
            if statement is None:
                skipped += 1
                continue
            try:
                async with admin.transaction():
                    await admin.execute(statement)
            except psycopg.Error:
                if admin.broken:
                    raise
                skipped += 1
    return skipped


def setting_statement(database: sql.Identifier, setting: DatabaseSetting) -> sql.Composed | None:
    if not SETTING_NAME_PATTERN.fullmatch(setting.name):
        return None
    if setting.name in LIST_QUOTED_SETTINGS:
        elements = split_list_setting(setting.value)
        if elements is None:
            return None
        values = sql.SQL(", ").join(sql.Literal(element) for element in elements)
    else:
        values = sql.Literal(setting.value)
    name = sql.SQL(".").join(sql.Identifier(part) for part in setting.name.split("."))
    return sql.SQL("ALTER DATABASE {} SET {} = {}").format(database, name, values)


def split_list_setting(value: str) -> list[str] | None:
    """The elements of a stored list setting, or None when it cannot be read as one.

    Elements are separated by commas; one in double quotes keeps its spaces and commas, with
    `""` for a quote inside it. Unquoted elements end at a comma or a space, and are kept as
    written.
    """
    elements = []
    length = len(value)

    def skip_spaces(at: int) -> int:
        while at < length and value[at].isspace():
            at += 1
        return at

    position = skip_spaces(0)
    if position == length:
        return []
    while True:
        if value[position] == '"':
            element = []
            position += 1
            while True:
                end = value.find('"', position)
                if end == -1:
                    return None
                element.append(value[position:end])
                if end + 1 < length and value[end + 1] == '"':
                    element.append('"')
                    position = end + 2
                    continue
                position = end + 1
                break
            elements.append("".join(element))
        else:
            start = position
            while position < length and value[position] != "," and not value[position].isspace():
                position += 1
            if position == start:
                return None
            elements.append(value[start:position])
        position = skip_spaces(position)
        if position == length:
            return elements
        if value[position] != ",":
            return None
        position = skip_spaces(position + 1)
        if position == length:
            return None
