"""The node's sessions on plugins_db, and how their failures are classified.

Two kinds of session, both with `require_auth=scram-sha-256` (a server that asks for any other
kind of authentication is refused before the password is sent), a connect timeout, and TCP
keepalives plus a user timeout, so a server that stops answering ends the session instead of
holding it open:

- **admin**: `plugins_admin` on the `postgres` database, never on a plugin's own database, so
  no trigger, operator or `search_path` entry a plugin plants can run with its privileges. Its
  `search_path` is `pg_catalog` from the start-up packet on, and `createrole_self_grant` is
  empty, so a role it creates never makes it a member of that role.
- **owner**: a plugin's owner role on that plugin's own database, logged in with the one-time
  password the migration runner gives it for one run. SQL a plugin wrote runs only here: with
  the owner as the session user, no `RESET ROLE` can lead back to `plugins_admin`.

A session either opens or raises `DatabaseUnreachableError`; inside it, an error raised by
psycopg leaves as `DatabaseUnreachableError` when the connection was lost, and as
`DatabaseProvisioningError` (reason `sql`) otherwise. No password, verifier or connection
string is ever part of an error message.
"""

import asyncio
import contextlib
import time
import unicodedata
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from typing import Literal

import psycopg
from src.shared.models.plugin_nodes import DesiredDatabaseServer

ADMIN_ROLE = "plugins_admin"
BACKUP_ROLE = "plugins_backup"
ADMIN_DATABASE = "postgres"
REQUIRED_AUTHENTICATION = "scram-sha-256"
CONNECT_TIMEOUT_SECONDS = 10
APPLICATION_NAME = "epicstaff-node"
ADMIN_SESSION_OPTIONS = (
    "-c search_path=pg_catalog -c statement_timeout=30000 -c createrole_self_grant="
)
OWNER_SESSION_OPTIONS = "-c statement_timeout=900000 -c lock_timeout=60000"
# A dead peer is noticed within about a minute: keepalives after 30 s idle, every 10 s, three
# missed; unacknowledged data gives up after 60 s.
_TCP_SETTINGS = {
    "keepalives": 1,
    "keepalives_idle": 30,
    "keepalives_interval": 10,
    "keepalives_count": 3,
    "tcp_user_timeout": 60_000,
}
_SESSION_POLL_SECONDS = 0.1
# SQLSTATEs meaning the server, not the statement, ended the session: connection exceptions
# (class 08), and the server shutting down or not accepting connections yet.
_CONNECTION_LOST_STATES = ("08", "57P01", "57P02", "57P03")
_MAX_ERROR_TEXT = 500

FailureReason = Literal["conflict", "assertion", "migration", "sql"]
Connect = Callable[..., Awaitable[psycopg.AsyncConnection]]


class DatabaseUnreachableError(Exception):
    """plugins_db cannot be reached, or the session was lost: trying again later may succeed."""


class DatabaseProvisioningError(Exception):
    """A permanent failure: the same attempt would fail the same way. The message is reported."""

    def __init__(self, reason: FailureReason, message: str):
        super().__init__(message)
        self.reason = reason


def describe_error(error: psycopg.Error) -> str:
    """`[SQLSTATE] message` of an error the server sent, or psycopg's own message, on one line.

    A plugin's SQL chooses the message (`RAISE EXCEPTION`), so control characters become spaces
    and runs of spaces one: it can never start a log line of its own.
    """
    if error.sqlstate:
        text = f"[{error.sqlstate}] {error.diag.message_primary or ''}"
    else:
        text = str(error)
    spaced = "".join(
        " " if unicodedata.category(character) in ("Cc", "Cs") else character for character in text
    )
    return " ".join(spaced.split())[:_MAX_ERROR_TEXT]


def scram_verifier(connection: psycopg.AsyncConnection, role: str, password: str) -> str:
    """The SCRAM-SHA-256 verifier of `password` for `role`, computed here, not by the server.

    A role's password is always sent as its verifier, so the clear password never reaches the
    server, its statement log or `pg_stat_activity`.
    """
    verifier = connection.pgconn.encrypt_password(
        password.encode(), role.encode(), REQUIRED_AUTHENTICATION.encode()
    )
    return verifier.decode("ascii")


class DatabaseConnector:
    """Opens the node's sessions on a plugin database server.

    `connect` is psycopg's `AsyncConnection.connect`; tests wrap it to see every connection.
    """

    def __init__(self, admin_password: str, *, connect: Connect = psycopg.AsyncConnection.connect):
        self._admin_password = admin_password
        self._connect = connect

    def admin_session(
        self, server: DesiredDatabaseServer
    ) -> contextlib.AbstractAsyncContextManager[psycopg.AsyncConnection]:
        """`plugins_admin` on `postgres`, in autocommit.

        Raises:
            DatabaseUnreachableError: The session could not be opened, or was lost.
            DatabaseProvisioningError: A statement failed (reason `sql`).
        """
        return self._session(
            server,
            dbname=ADMIN_DATABASE,
            user=ADMIN_ROLE,
            password=self._admin_password,
            options=ADMIN_SESSION_OPTIONS,
        )

    def owner_session(
        self, server: DesiredDatabaseServer, database_name: str, owner_role: str, password: str
    ) -> contextlib.AbstractAsyncContextManager[psycopg.AsyncConnection]:
        """A plugin's owner role on its own database, in autocommit.

        Raises:
            DatabaseUnreachableError: The session could not be opened, or was lost.
            DatabaseProvisioningError: A statement failed (reason `sql`).
        """
        return self._session(
            server,
            dbname=database_name,
            user=owner_role,
            password=password,
            options=OWNER_SESSION_OPTIONS,
        )

    @contextlib.asynccontextmanager
    async def _session(
        self, server: DesiredDatabaseServer, **parameters: str
    ) -> AsyncIterator[psycopg.AsyncConnection]:
        try:
            connection = await self._connect(
                host=server.host,
                port=server.port,
                require_auth=REQUIRED_AUTHENTICATION,
                connect_timeout=CONNECT_TIMEOUT_SECONDS,
                application_name=APPLICATION_NAME,
                autocommit=True,
                **_TCP_SETTINGS,
                **parameters,
            )
        except psycopg.Error as error:
            raise DatabaseUnreachableError(
                f"plugins_db at {server.host}:{server.port} cannot be reached: "
                f"{describe_error(error)}"
            ) from None
        try:
            yield connection
        except psycopg.Error as error:
            raise session_error(error, connection) from None
        finally:
            await connection.close()


def session_error(
    error: psycopg.Error, connection: psycopg.AsyncConnection
) -> DatabaseUnreachableError | DatabaseProvisioningError:
    """Classify an error raised inside an open session."""
    if connection.broken or (error.sqlstate or "").startswith(_CONNECTION_LOST_STATES):
        return DatabaseUnreachableError(
            f"the session on plugins_db was lost: {describe_error(error)}"
        )
    return DatabaseProvisioningError("sql", describe_error(error))


async def end_sessions(
    admin: psycopg.AsyncConnection, roles: Sequence[str], *, within_seconds: float
) -> list[int]:
    """End every session that logged in as one of `roles`; return the pids still there after.

    `plugins_admin` may end them through `pg_signal_backend`. A session that switched to another
    role with `SET ROLE` still counts under the role it logged in as.
    """
    deadline = time.monotonic() + within_seconds
    while True:
        cursor = await admin.execute(
            "SELECT pid, pg_catalog.pg_terminate_backend(pid) FROM pg_catalog.pg_stat_activity "
            "WHERE usename = ANY(%s) AND pid <> pg_catalog.pg_backend_pid()",
            (list(roles),),
        )
        remaining = [row[0] for row in await cursor.fetchall()]
        if not remaining or time.monotonic() >= deadline:
            return remaining
        await asyncio.sleep(_SESSION_POLL_SECONDS)
