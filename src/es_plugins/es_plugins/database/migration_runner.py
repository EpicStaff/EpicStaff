"""Apply a plugin's database migrations with its owner role as the session user.

The migrations are the package's `database/migrations/NNN_<name>.sql`, read from the verified
package (`read_migrations`: every file checked against `CONTENTS.json`), applied in name order:

1. As `plugins_admin`, from `postgres`, the owner is opened for this run only: LOGIN with the
   verifier of a fresh random password, `CONNECTION LIMIT 1`, `VALID UNTIL` ten minutes on.
2. As the owner, on the plugin's database, the ledger `_epicstaff.migrations` is created if it
   is missing.
3. A file already in the ledger with the same sha256 is skipped; with another sha256 the run
   stops ("changed after it was applied"). Any other file runs whole, without parameters (so
   multi-statement files and `DO` blocks work), with `MIGRATION_PLACEHOLDERS` replaced by the
   quoted role names, in one transaction together with its ledger row. An error rolls that file
   back and stops the run.
4. Always, whether the run succeeded or not: the owner session is closed and the owner goes back
   to NOLOGIN without a password. An agent that dies in between leaves the owner LOGIN only with
   a password nobody knows, until `VALID UNTIL` passes, the next provisioning, or the limits
   watchdog, whichever comes first.

The ledger guards against mistakes, not attacks: the owner owns it, so a migration can rewrite
it. A `COMMIT` inside a migration ends its one-transaction guarantee.
"""

import contextlib
import re
import secrets
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import psycopg
from loguru import logger
from psycopg import sql
from src.shared.models.plugin_nodes import DesiredDatabase

from es_plugins.database.connections import (
    DatabaseConnector,
    DatabaseProvisioningError,
    DatabaseUnreachableError,
    describe_error,
    scram_verifier,
    session_error,
)

# Each `${name}` in a migration becomes the quoted name of the role DesiredDatabase.<name> names.
MIGRATION_PLACEHOLDERS = ("owner_role", "app_role", "job_role")
MIGRATIONS_LEDGER_SCHEMA = "_epicstaff"
MIGRATIONS_LEDGER_TABLE = "migrations"
MIGRATION_NAME_PATTERN = re.compile(r"^[0-9]{3}_[a-z0-9][a-z0-9_]*\.sql$")
OWNER_LOGIN_WINDOW = timedelta(minutes=10)
_BYTE_ORDER_MARK = "﻿"

_LEDGER = sql.SQL("{}.{}").format(
    sql.Identifier(MIGRATIONS_LEDGER_SCHEMA), sql.Identifier(MIGRATIONS_LEDGER_TABLE)
)
_CREATE_LEDGER = sql.SQL(
    "CREATE SCHEMA IF NOT EXISTS {schema}; "
    "CREATE TABLE IF NOT EXISTS {ledger} ("
    "name text PRIMARY KEY, sha256 text NOT NULL, applied_at timestamptz NOT NULL DEFAULT now())"
).format(schema=sql.Identifier(MIGRATIONS_LEDGER_SCHEMA), ledger=_LEDGER)


@dataclass(frozen=True)
class Migration:
    """One migration file of a verified package."""

    name: str
    """The file name, `NNN_<name>.sql`."""

    sha256: str
    """Of the file's bytes as packaged: the digest `CONTENTS.json` lists for it."""

    content: bytes = field(repr=False)


@dataclass(frozen=True)
class MigrationRun:
    ledger: tuple[str, ...]
    """Every migration the ledger lists after the run, in the order they were applied."""

    applied: int
    """How many of them this run applied."""


async def open_owner_login(
    admin: psycopg.AsyncConnection, owner_role: str, password: str, valid_until: datetime
) -> None:
    """Let the owner log in once, with `password`, until `valid_until`."""
    await admin.execute(
        sql.SQL("ALTER ROLE {} LOGIN PASSWORD {} CONNECTION LIMIT 1 VALID UNTIL {}").format(
            sql.Identifier(owner_role),
            sql.Literal(scram_verifier(admin, owner_role, password)),
            sql.Literal(valid_until.isoformat()),
        )
    )


async def close_owner_login(admin: psycopg.AsyncConnection, owner_role: str) -> None:
    """Put the owner back to NOLOGIN, without a password and without a connection limit."""
    await admin.execute(
        sql.SQL(
            "ALTER ROLE {} NOLOGIN PASSWORD NULL CONNECTION LIMIT -1 VALID UNTIL 'infinity'"
        ).format(sql.Identifier(owner_role))
    )


class MigrationRunner:
    def __init__(
        self,
        connector: DatabaseConnector,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        self._connector = connector
        self._clock = clock

    async def run(
        self,
        admin: psycopg.AsyncConnection,
        desired: DesiredDatabase,
        migrations: Sequence[Migration],
    ) -> MigrationRun:
        """Apply the migrations the ledger does not list yet; see the module docstring.

        `admin` is an open admin session on the plugin's server; it opens and closes the owner.

        Raises:
            DatabaseProvisioningError: A migration failed or changed (reason `migration`), or
                another statement failed (reason `sql`).
            DatabaseUnreachableError: A session could not be opened, or was lost.
        """
        password = secrets.token_urlsafe(32)
        owner_role = desired.owner_role
        await open_owner_login(admin, owner_role, password, self._clock() + OWNER_LOGIN_WINDOW)
        try:
            async with self._connector.owner_session(
                desired.server, desired.database_name, owner_role, password
            ) as owner:
                run = await self._apply(owner, desired, migrations)
        except BaseException:
            # The run's own failure is the one to report; the owner is closed all the same.
            try:
                await close_owner_login(admin, owner_role)
            except psycopg.Error as error:
                logger.warning(
                    "Could not set {} back to NOLOGIN after a failed migration run: {}",
                    owner_role,
                    describe_error(error),
                )
            raise
        await close_owner_login(admin, owner_role)
        return run

    async def _apply(
        self,
        owner: psycopg.AsyncConnection,
        desired: DesiredDatabase,
        migrations: Sequence[Migration],
    ) -> MigrationRun:
        await _in_transaction(owner, _CREATE_LEDGER)
        cursor = await owner.execute(sql.SQL("SELECT name, sha256 FROM {}").format(_LEDGER))
        recorded = dict(await cursor.fetchall())
        replacements = {
            "${" + name + "}": sql.Identifier(getattr(desired, name)).as_string(owner)
            for name in MIGRATION_PLACEHOLDERS
        }
        applied = 0
        for migration in sorted(migrations, key=lambda migration: migration.name):
            if migration.name in recorded:
                if recorded[migration.name] != migration.sha256:
                    raise DatabaseProvisioningError(
                        "migration", f"{migration.name} changed after it was applied"
                    )
                continue
            await self._apply_one(owner, migration, _migration_text(migration, replacements))
            applied += 1
        cursor = await owner.execute(
            sql.SQL("SELECT name FROM {} ORDER BY applied_at, name").format(_LEDGER)
        )
        return MigrationRun(
            ledger=tuple(row[0] for row in await cursor.fetchall()), applied=applied
        )

    @staticmethod
    async def _apply_one(owner: psycopg.AsyncConnection, migration: Migration, text: str) -> None:
        try:
            await owner.execute("BEGIN")
            # No parameters: psycopg sends the text as one simple query, every statement in it.
            await owner.execute(text)
            await owner.execute(
                sql.SQL("INSERT INTO {} (name, sha256) VALUES (%s, %s)").format(_LEDGER),
                (migration.name, migration.sha256),
            )
            await owner.execute("COMMIT")
        except psycopg.Error as error:
            failure = session_error(error, owner)
            if isinstance(failure, DatabaseUnreachableError):
                raise failure from None
            with contextlib.suppress(psycopg.Error):
                await owner.execute("ROLLBACK")
            raise DatabaseProvisioningError(
                "migration", f"{migration.name}{_line_of(text, error)}: {describe_error(error)}"
            ) from None


def _migration_text(migration: Migration, replacements: dict[str, str]) -> str:
    try:
        text = migration.content.decode("utf-8")
    except UnicodeDecodeError:
        raise DatabaseProvisioningError(
            "migration", f"{migration.name} is not UTF-8 text"
        ) from None
    text = text.removeprefix(_BYTE_ORDER_MARK)
    for placeholder, quoted in replacements.items():
        text = text.replace(placeholder, quoted)
    return text


def _line_of(text: str, error: psycopg.Error) -> str:
    """` line <n>` where the server placed the error; empty when it named no position."""
    position = error.diag.statement_position
    if not position:
        return ""
    # The position counts characters from 1; a placeholder never spans lines, so the line of the
    # substituted text is the line of the file.
    line = text[: int(position) - 1].count("\n") + 1
    return f" line {line}"


async def _in_transaction(connection: psycopg.AsyncConnection, statement: sql.Composable) -> None:
    async with connection.transaction():
        await connection.execute(statement)
