"""Apply a plugin's database migrations with its owner role as the session user.

The migrations are the package's `database/migrations/NNN_<name>.sql`, read from the verified
package (`read_migrations`: every file checked against `CONTENTS.json`), applied in name order:

1. As `plugins_admin`, from `postgres`, the owner is opened for this run only: every setting it
   stored for itself is removed, then LOGIN with the verifier of a fresh random password,
   `CONNECTION LIMIT 1`, `VALID UNTIL` ten minutes on.
2. As the owner, on the plugin's database, the ledger `_epicstaff.migrations` is created if it
   is missing.
3. A file already in the ledger with the same sha256 is skipped; with another sha256 the run
   stops ("changed after it was applied"). Any other file runs whole, without parameters (so
   multi-statement files and `DO` blocks work), with `MIGRATION_PLACEHOLDERS` replaced by the
   quoted role names, in one transaction together with its ledger row. An error rolls that file
   back and stops the run, and so does a file that ends the transaction itself (`COMMIT` or
   `ROLLBACK`): it is refused before its ledger row is written, though what it committed stays.
4. Always, whether the run succeeded or not: the owner session is closed, the owner goes back to
   NOLOGIN without a password, and every session the owner still has is ended. A migration runs
   as the owner, and any role may change its own password, so a migration can give the owner a
   password of its own and open more sessions with it while the run lasts. An agent that dies
   in between leaves the owner able to log in, with this run's password or one a migration set,
   until `VALID UNTIL` passes, the next provisioning, or the limits watchdog, whichever comes
   first.

The ledger guards against mistakes, not attacks: the owner owns it, so a migration can rewrite
it. It is read bounded (at most `MAX_APPLIED_MIGRATIONS + 1` rows, every column cut at
`MAX_MIGRATION_NAME_LENGTH + 1` characters) and only entries `is_reportable_ledger_entry` accepts
are kept, so no row a migration writes can exhaust the agent's memory or make its report
invalid. A run reads it again when a migration fails, so the failure carries what the database
now holds: EpicStaff decides from it whether an upgrade can still be cancelled.
"""

import asyncio
import contextlib
import secrets
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import psycopg
from epicstaff_plugin.contracts.database import (
    MIGRATION_PLACEHOLDERS,
    MIGRATIONS_LEDGER_SCHEMA,
    MIGRATIONS_LEDGER_TABLE,
)
from epicstaff_plugin.package_layout import MAX_MIGRATION_NAME_LENGTH
from loguru import logger
from psycopg import sql
from psycopg.pq import TransactionStatus
from src.shared.models.plugin_nodes import (
    MAX_APPLIED_MIGRATIONS,
    DesiredDatabase,
    LedgerEntry,
    is_reportable_ledger_entry,
)

from es_plugins.database.connections import (
    DatabaseConnector,
    DatabaseProvisioningError,
    DatabaseUnreachableError,
    describe_error,
    end_sessions,
    scram_verifier,
    session_error,
)
from es_plugins.database.database_attributes import reset_role_settings

OWNER_LOGIN_WINDOW = timedelta(minutes=10)
# Long enough for a session ended with pg_terminate_backend to go.
OWNER_SESSIONS_END_SECONDS = 10.0
OWNER_CANCEL_SECONDS = 5.0
_BYTE_ORDER_MARK = "\ufeff"

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
    ledger: tuple[LedgerEntry, ...]
    """Every migration the ledger lists after the run, with its digest, in the order they were
    applied."""

    applied: int
    """How many of them this run applied."""


async def open_owner_login(
    admin: psycopg.AsyncConnection, owner_role: str, password: str, valid_until: datetime
) -> None:
    """Let the owner log in once, with `password`, until `valid_until`.

    Every setting the owner stored for itself is removed first: a migration may have stored one
    that refuses the login itself (`local_preload_libraries`) or breaks what runs after it.
    """
    await reset_role_settings(admin, owner_role)
    await admin.execute(
        sql.SQL("ALTER ROLE {} LOGIN PASSWORD {} CONNECTION LIMIT 1 VALID UNTIL {}").format(
            sql.Identifier(owner_role),
            sql.Literal(scram_verifier(admin, owner_role, password)),
            sql.Literal(valid_until.isoformat()),
        )
    )


async def close_owner_login(admin: psycopg.AsyncConnection, owner_role: str) -> None:
    """Put the owner back to NOLOGIN, without a password and without a connection limit, and end
    every session it still has.

    NOLOGIN stops new sessions only; a session opened before it, with this run's password or one a
    migration set, is ended here.

    Raises:
        DatabaseProvisioningError: Reason `assertion`: a session of the owner did not end.
    """
    await admin.execute(
        sql.SQL(
            "ALTER ROLE {} NOLOGIN PASSWORD NULL CONNECTION LIMIT -1 VALID UNTIL 'infinity'"
        ).format(sql.Identifier(owner_role))
    )
    remaining = await end_sessions(admin, [owner_role], within_seconds=OWNER_SESSIONS_END_SECONDS)
    if remaining:
        raise DatabaseProvisioningError(
            "assertion",
            f"a session of {owner_role} did not end within {OWNER_SESSIONS_END_SECONDS:.0f} s",
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
                try:
                    run = await self._apply(owner, desired, migrations)
                except asyncio.CancelledError:
                    # Provisioning ran out of time, or the agent stops: stop the statement on the
                    # server too, not only the wait for it here.
                    with contextlib.suppress(psycopg.Error, OSError):
                        await owner.cancel_safe(timeout=OWNER_CANCEL_SECONDS)
                    raise
        except BaseException:
            # The run's own failure is the one to report; the owner is closed all the same.
            try:
                await close_owner_login(admin, owner_role)
            except (psycopg.Error, DatabaseProvisioningError) as error:
                logger.warning(
                    "Could not close the owner {} after a failed migration run: {}",
                    owner_role,
                    describe_error(error) if isinstance(error, psycopg.Error) else error,
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
        recorded = dict(await _read_ledger(owner, ["name", "sha256"]))
        replacements = {
            # Each `${name}` becomes the quoted name of the role DesiredDatabase.<name> names.
            "${" + name + "}": sql.Identifier(getattr(desired, name)).as_string(owner)
            for name in MIGRATION_PLACEHOLDERS
        }
        applied = 0
        try:
            for migration in sorted(migrations, key=lambda migration: migration.name):
                if migration.name in recorded:
                    if recorded[migration.name] != migration.sha256:
                        raise DatabaseProvisioningError(
                            "migration", f"{migration.name} changed after it was applied"
                        )
                    continue
                await self._apply_one(owner, migration, _migration_text(migration, replacements))
                applied += 1
        except DatabaseProvisioningError as failure:
            # The files applied before this one stay applied. Unknown (None) if the session
            # cannot read the ledger any more.
            with contextlib.suppress(psycopg.Error):
                failure.ledger = await reportable_ledger(owner)
            raise
        return MigrationRun(ledger=await reportable_ledger(owner), applied=applied)

    @staticmethod
    async def _apply_one(owner: psycopg.AsyncConnection, migration: Migration, text: str) -> None:
        try:
            await owner.execute("BEGIN")
            transaction = await _transaction_id(owner)
            # No parameters: psycopg sends the text as one simple query, every statement in it.
            await owner.execute(text)
            # A file that ended the transaction itself is caught here, before its ledger row:
            # either none is open any more, or a BEGIN after its COMMIT opened another one.
            if (
                owner.info.transaction_status != TransactionStatus.INTRANS
                or await _transaction_id(owner) != transaction
            ):
                with contextlib.suppress(psycopg.Error):
                    await owner.execute("ROLLBACK")
                raise DatabaseProvisioningError(
                    "migration",
                    f"{migration.name} ends its own transaction (COMMIT or ROLLBACK); a migration "
                    "runs in the one transaction the node opens for it",
                )
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


async def _transaction_id(owner: psycopg.AsyncConnection) -> int:
    cursor = await owner.execute("SELECT pg_catalog.pg_current_xact_id()::text::bigint")
    return (await cursor.fetchone())[0]


async def _read_ledger(owner: psycopg.AsyncConnection, columns: list[str]) -> list[tuple]:
    """The ledger's rows, oldest first, read so that no row a migration wrote can be large.

    Every column is read as text cut to `MAX_MIGRATION_NAME_LENGTH + 1` characters, whatever a
    migration changed its type to, and at most `MAX_APPLIED_MIGRATIONS + 1` rows.
    """
    cut = sql.SQL(", ").join(
        sql.SQL("pg_catalog.left({}::text, {})").format(
            sql.Identifier(column), sql.Literal(MAX_MIGRATION_NAME_LENGTH + 1)
        )
        for column in columns
    )
    cursor = await owner.execute(
        sql.SQL("SELECT {} FROM {} ORDER BY applied_at, name LIMIT {}").format(
            cut, _LEDGER, sql.Literal(MAX_APPLIED_MIGRATIONS + 1)
        )
    )
    return await cursor.fetchall()


async def reportable_ledger(owner: psycopg.AsyncConnection) -> tuple[LedgerEntry, ...]:
    """The ledger as a report may carry it, read on an owner session of the plugin's database."""
    rows = await _read_ledger(owner, ["name", "sha256"])
    ledger = tuple(
        LedgerEntry(name=name, sha256=sha256)
        for name, sha256 in rows
        if is_reportable_ledger_entry(name, sha256)
    )
    dropped = len(rows) - len(ledger)
    if dropped or len(rows) > MAX_APPLIED_MIGRATIONS:
        # Counts only: a row's content is the plugin's.
        logger.warning(
            "plugins.database.ledger_entries_dropped count={} more_than_read={}",
            dropped,
            "true" if len(rows) > MAX_APPLIED_MIGRATIONS else "false",
        )
    return ledger[:MAX_APPLIED_MIGRATIONS]


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
