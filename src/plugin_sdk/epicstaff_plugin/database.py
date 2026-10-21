"""The plugin's own database, for a backend whose manifest has a `database` section.

The node sets the database up before the backend first starts and hands the backend two
environment variables: `DATABASE_URL`, a `postgresql://` URL that logs in as the plugin's app
role, and `EPICSTAFF_PLUGIN_DB_CONNECTIONS`, the most connections that role may hold at once.
One database serves every organization the plugin is granted to. `org_transaction` tells the
tables' row-level security policies which organization a transaction works for, through the
setting `app.org_id`.

The SDK depends on no database driver. `org_transaction` takes a psycopg 3 `AsyncConnection`
(`psycopg[binary,pool]` in the backend's lock), or anything with the same `transaction()` and
`execute()`.
"""

import os
from collections.abc import AsyncIterator, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from contextvars import ContextVar
from typing import Any, Protocol

from epicstaff_plugin.contracts.runtime import (
    DATABASE_CONNECTIONS_ENVIRONMENT_VARIABLE,
    DATABASE_URL_ENVIRONMENT_VARIABLE,
)

ORG_ID_SETTING = "app.org_id"
# `true` makes the value local to the transaction: it is gone when the transaction ends, so a
# pooled connection never carries one organization's id into the next transaction.
_SET_ORG_ID = f"SELECT pg_catalog.set_config('{ORG_ID_SETTING}', %s, true)"
# The organization of the `org_transaction` open in this task, if any. A nested one is a
# savepoint, and the setting it makes outlives the savepoint, so another organization's would
# stay set for the rest of the outer transaction.
_open_org_id: ContextVar[int | None] = ContextVar("epicstaff_plugin_open_org_id", default=None)


class DatabaseUnavailable(Exception):  # noqa: N818 (named like ServiceAccountUnavailable)
    """The process has no plugin database: its manifest declares none, or it runs off the node."""


class NestedOrgTransactionError(RuntimeError):
    """An `org_transaction` for one organization was opened inside one for another."""


class AsyncTransactionalConnection(Protocol):
    """What `org_transaction` needs of a connection; psycopg 3's `AsyncConnection` has it."""

    def transaction(self) -> AbstractAsyncContextManager[Any]: ...

    async def execute(self, query: str, params: Sequence[Any]) -> Any: ...


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
    same organization is a savepoint, and one for another organization is refused, on any
    connection. A task started inside the block inherits that organization.

    Raises:
        ValueError: `org_id` is not a positive integer. Nothing is sent to the database.
        NestedOrgTransactionError: An `org_transaction` for another organization is open in
            this task. Nothing is sent to the database.
    """
    if isinstance(org_id, bool) or not isinstance(org_id, int) or org_id < 1:
        raise ValueError(f"an organization id is a positive integer, not {org_id!r}")
    open_org_id = _open_org_id.get()
    if open_org_id is not None and open_org_id != org_id:
        raise NestedOrgTransactionError(
            f"an org_transaction for organization {open_org_id} is open; finish it before "
            f"starting one for organization {org_id}"
        )
    token = _open_org_id.set(org_id)
    try:
        async with connection.transaction():
            await connection.execute(_SET_ORG_ID, (str(org_id),))
            yield connection
    finally:
        _open_org_id.reset(token)
