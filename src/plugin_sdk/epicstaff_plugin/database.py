"""The plugin's own database, for a backend whose manifest has a `database` section.

The node sets the database up before the backend first starts and hands the backend two
environment variables: `DATABASE_URL`, a `postgresql://` URL that logs in as the plugin's app
role, and `EPICSTAFF_PLUGIN_DB_CONNECTIONS`, the most connections that role may hold at once.
One database serves every organization the plugin is granted to.

Two kinds of transaction set what the row-level security policies of a transaction see:

- `org_transaction` works for one organization, through the setting `app.org_id`. Requests
  use it.
- `job_transaction` works as the plugin's job role, across organizations, under the policies
  the plugin's migrations give that role. Maintenance tasks use it, to delete expired rows of
  every organization, for example.

Both settings are local to the transaction. A savepoint does not end them, so each kind starts
only on a connection with no transaction open, or nests in an open block of its own kind on
the same connection: a fresh connection from the pool is always right.

The SDK depends on no database driver. Both take a psycopg 3 `AsyncConnection`
(`psycopg[binary,pool]` in the backend's lock), or anything with the same `transaction()`,
`execute()` and `info`.
"""

import os
from collections.abc import AsyncIterator, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Protocol

from epicstaff_plugin.contracts.runtime import (
    DATABASE_CONNECTIONS_ENVIRONMENT_VARIABLE,
    DATABASE_URL_ENVIRONMENT_VARIABLE,
)

ORG_ID_SETTING = "app.org_id"
# The suffixes of the role names the node gives every plugin database: the backend logs in as
# `<id_>_app`, which may SET ROLE to `<id_>_job`.
APP_ROLE_SUFFIX = "_app"
JOB_ROLE_SUFFIX = "_job"
# `true` makes each value local to the transaction: it is gone when the transaction ends, so a
# pooled connection never carries an organization or a role into the next transaction.
_SET_ORG_ID = f"SELECT pg_catalog.set_config('{ORG_ID_SETTING}', %s, true)"
_SET_ROLE = "SELECT pg_catalog.set_config('role', %s, true)"
# psycopg's `pq.TransactionStatus.IDLE`: the connection has no transaction open.
_IDLE = 0


class DatabaseUnavailable(Exception):  # noqa: N818 (named like ServiceAccountUnavailable)
    """The process has no plugin database: its manifest declares none, or it runs off the node."""


class NestedOrgTransactionError(RuntimeError):
    """A transaction was opened inside an open one of another kind or organization.

    An `org_transaction` for one organization inside one for another, or an `org_transaction`
    and a `job_transaction` inside each other.
    """


class ConnectionInTransactionError(RuntimeError):
    """The connection already has a transaction open that no open block of this task started.

    Its organization or role would outlive the block, so the block refuses it.
    """


class TransactionalConnectionInfo(Protocol):
    """What the helpers read of a connection's state; psycopg 3's `ConnectionInfo` has it."""

    @property
    def transaction_status(self) -> int: ...

    @property
    def user(self) -> str: ...


class AsyncTransactionalConnection(Protocol):
    """What the helpers need of a connection; psycopg 3's `AsyncConnection` has it."""

    @property
    def info(self) -> TransactionalConnectionInfo: ...

    def transaction(self) -> AbstractAsyncContextManager[Any]: ...

    async def execute(self, query: str, params: Sequence[Any]) -> Any: ...


@dataclass(frozen=True)
class _OpenBlock:
    """The `org_transaction` or `job_transaction` blocks open in this task."""

    org_id: int | None
    """The organization of the open `org_transaction` blocks; None for `job_transaction`."""

    connections: tuple[AsyncTransactionalConnection, ...]
    """The connections those blocks hold a transaction open on."""

    def holds(self, connection: AsyncTransactionalConnection) -> bool:
        return any(held is connection for held in self.connections)

    def describe(self) -> str:
        if self.org_id is None:
            return "a job_transaction"
        return f"an org_transaction for organization {self.org_id}"


_open_block: ContextVar[_OpenBlock | None] = ContextVar("epicstaff_plugin_open_block", default=None)


def database_url() -> str:
    """Return the plugin database's URL, which logs in as the plugin's app role.

    It holds the role's password: never log it or show it.

    Raises:
        DatabaseUnavailable: `DATABASE_URL` is not set.
    """
    value = os.environ.get(DATABASE_URL_ENVIRONMENT_VARIABLE)
    if not value:
        raise DatabaseUnavailable(
            f"{DATABASE_URL_ENVIRONMENT_VARIABLE} is not set; the EpicStaff node sets it for a "
            "plugin whose manifest has a database section"
        )
    return value


def connection_limit() -> int:
    """Return how many connections the app role may hold at once; size your pool to it.

    Raises:
        DatabaseUnavailable: `EPICSTAFF_PLUGIN_DB_CONNECTIONS` is not set, or is not a
            positive integer.
    """
    value = os.environ.get(DATABASE_CONNECTIONS_ENVIRONMENT_VARIABLE, "")
    if not (value.isascii() and value.isdecimal() and int(value) > 0):
        raise DatabaseUnavailable(
            f"{DATABASE_CONNECTIONS_ENVIRONMENT_VARIABLE} must be a positive integer, not "
            f"{value!r}; the EpicStaff node sets it for a plugin whose manifest has a database "
            "section"
        )
    return int(value)


@asynccontextmanager
async def org_transaction[Connection: AsyncTransactionalConnection](
    connection: Connection, org_id: int
) -> AsyncIterator[Connection]:
    """Run a transaction for one organization, and yield the connection.

    Opens `connection.transaction()` and sets `app.org_id` to the organization's id, as text,
    for that transaction only. Row-level security policies that compare a row's organization
    with `current_setting('app.org_id', true)` then show and accept only that organization's
    rows. The transaction commits when the block ends, and rolls back when it raises.

    One organization at a time in a task: inside an open `org_transaction`, another one for the
    same organization is a savepoint on the same connection, or a transaction of its own on a
    connection with none open; one for another organization is refused, on any connection. A
    task started inside the block inherits that organization.

    Raises:
        ValueError: `org_id` is not a positive integer.
        NestedOrgTransactionError: An `org_transaction` for another organization, or a
            `job_transaction`, is open in this task.
        ConnectionInTransactionError: The connection has a transaction open that is not an
            `org_transaction` for this organization opened on it in this task. psycopg opens one
            by itself for any query outside a transaction block.

        Each is raised before anything is sent to the database.
    """
    if isinstance(org_id, bool) or not isinstance(org_id, int) or org_id < 1:
        raise ValueError(f"an organization id is a positive integer, not {org_id!r}")
    async with _transaction_block(
        connection,
        org_id,
        f"an org_transaction for organization {org_id}",
        _SET_ORG_ID,
        str(org_id),
    ):
        yield connection


@asynccontextmanager
async def job_transaction[Connection: AsyncTransactionalConnection](
    connection: Connection,
) -> AsyncIterator[Connection]:
    """Run a transaction as the plugin's job role, across organizations, and yield the connection.

    Opens `connection.transaction()` and switches to the job role (`<id_>_job`, named after the
    app role the connection logs in as) for that transaction only, as `SET LOCAL ROLE` does. The
    transaction then has exactly what the plugin's migrations grant `${job_role}`, under the
    row-level security policies they give that role, and no organization set. Keep it short:
    a maintenance task opens one per batch of work.

    Inside an open `job_transaction`, another one on the same connection is a savepoint. A task
    started inside the block inherits it.

    Raises:
        ValueError: The connection does not log in as the plugin's app role (`<id_>_app`).
        NestedOrgTransactionError: An `org_transaction` is open in this task.
        ConnectionInTransactionError: The connection has a transaction open that is not a
            `job_transaction` opened on it in this task.

        Each is raised before anything is sent to the database.
    """
    user = connection.info.user
    if not user.endswith(APP_ROLE_SUFFIX) or user == APP_ROLE_SUFFIX:
        raise ValueError(
            f"a job_transaction needs a connection that logs in as the plugin's app role "
            f"(<id>{APP_ROLE_SUFFIX}), not {user!r}"
        )
    job_role = user.removesuffix(APP_ROLE_SUFFIX) + JOB_ROLE_SUFFIX
    async with _transaction_block(connection, None, "a job_transaction", _SET_ROLE, job_role):
        yield connection


@asynccontextmanager
async def _transaction_block(
    connection: AsyncTransactionalConnection,
    org_id: int | None,
    description: str,
    setting_query: str,
    setting_value: str,
) -> AsyncIterator[None]:
    open_block = _open_block.get()
    if open_block is not None and open_block.org_id != org_id:
        raise NestedOrgTransactionError(
            f"{open_block.describe()} is open; finish it before starting {description}"
        )
    held = open_block is not None and open_block.holds(connection)
    if connection.info.transaction_status != _IDLE and not held:
        raise ConnectionInTransactionError(
            f"the connection already has a transaction open, so {description} would outlive "
            "its block; commit or roll it back first, or take a fresh connection from the pool"
        )
    connections = open_block.connections if open_block is not None else ()
    token = _open_block.set(
        _OpenBlock(org_id=org_id, connections=connections if held else (*connections, connection))
    )
    try:
        async with connection.transaction():
            await connection.execute(setting_query, (setting_value,))
            yield
    finally:
        _open_block.reset(token)
