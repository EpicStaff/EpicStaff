"""Weather's own database, which the node sets up before the backend first starts.

The node runs `database/migrations/` and passes the database's address in `DATABASE_URL`, and
how many connections the backend may hold in `EPICSTAFF_PLUGIN_DB_CONNECTIONS`. Every table
has row-level security on `org_id`, and every query runs in `WeatherDatabase.transaction`, so
a query reads and writes only the rows of the organization it is given, whatever its SQL says.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from epicstaff_plugin.database import connection_limit, database_url, org_transaction
from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

Connection = AsyncConnection[dict[str, Any]]


class WeatherDatabase:
    """A pool of connections as the plugin's app role, each query in one organization's transaction."""

    def __init__(self, pool: AsyncConnectionPool[Connection]):
        self._pool = pool

    @classmethod
    async def open(cls) -> "WeatherDatabase":
        """Open a pool sized to the role's connection limit, once one connection works.

        Raises:
            DatabaseUnavailable: The node gave this process no database.
            psycopg_pool.PoolTimeout: No connection opened within 30 seconds.
        """
        pool = AsyncConnectionPool(
            database_url(),
            min_size=1,
            # PostgreSQL refuses the role any connection over its limit.
            max_size=connection_limit(),
            kwargs={"row_factory": dict_row},
            open=False,
        )
        await pool.open(wait=True)
        return cls(pool)

    @asynccontextmanager
    async def transaction(self, org_id: int) -> AsyncIterator[Connection]:
        """Yield a connection in a transaction that sees only `org_id`'s rows.

        The transaction commits when the block ends and rolls back when it raises.
        """
        async with self._pool.connection() as connection, org_transaction(connection, org_id):
            yield connection

    async def close(self) -> None:
        await self._pool.close()
