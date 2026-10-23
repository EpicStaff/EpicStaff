"""Deleting what Weather keeps only for a while: forecast runs after 7 days, expired popup results.

Requests never delete old rows. Once an hour, while the backend runs, `RetentionPurge` deletes
them for every organization at once, as the plugin's job role
(`WeatherDatabase.job_transaction`). The rule for what is old is in the job role's policies
(`database/migrations/002_retention.sql`), so these statements cannot reach a live row.

The purge goes in batches of about `PURGE_BATCH_ROWS` rows, oldest first along the timestamp
index, each batch in a transaction of its own. Each batch starts after the timestamp the one
before it ended at, so it finds its rows through the index however much has piled up, instead
of reading the whole table again. A batch stays well inside the database's statement timeout
and holds its locks only briefly. Rows sharing the timestamp a batch ends at go with that
batch, so a batch can be a little larger.
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime

from weather_plugin.database import WeatherDatabase

PURGE_INTERVAL_SECONDS = 3600
PURGE_BATCH_ROWS = 5000


@dataclass(frozen=True)
class PurgeStatements:
    """The statements that delete one table's expired rows, in batches along `column`'s index."""

    table: str
    column: str

    @property
    def batch_end(self) -> str:
        """The timestamp of the batch's last row: `%(offset)s` rows after `%(after)s`, or none."""
        return (
            f"SELECT {self.column} FROM {self.table} WHERE {self.column} > %(after)s::timestamptz"
            f" ORDER BY {self.column} OFFSET %(offset)s LIMIT 1"
        )

    @property
    def delete_batch(self) -> str:
        """Delete the rows after `%(after)s` up to the batch's last timestamp, `%(until)s`."""
        return (
            f"DELETE FROM {self.table} WHERE {self.column} > %(after)s::timestamptz"
            f" AND {self.column} <= %(until)s::timestamptz"
        )

    @property
    def delete_rest(self) -> str:
        """Delete every row after `%(after)s`: fewer than a batch are left."""
        return f"DELETE FROM {self.table} WHERE {self.column} > %(after)s::timestamptz"


# The policies limit every statement to expired rows.
PURGES = (
    PurgeStatements("weather.forecast_runs", "created_at"),
    PurgeStatements("weather.popup_results", "expires_at"),
)
# Before every timestamp: the first batch starts at the oldest row.
_FROM_THE_START = "-infinity"

logger = logging.getLogger(__name__)


class RetentionPurge:
    """Deletes expired rows of every organization."""

    def __init__(self, database: WeatherDatabase, *, batch_rows: int = PURGE_BATCH_ROWS):
        self._database = database
        self._batch_rows = batch_rows

    async def run_once(self) -> dict[str, int]:
        """Delete every expired row now, in batches, and return how many went from each table."""
        return {purge.table: await self._purge(purge) for purge in PURGES}

    async def _purge(self, purge: PurgeStatements) -> int:
        deleted = 0
        after: datetime | str = _FROM_THE_START
        while True:
            async with self._database.job_transaction() as connection:
                cursor = await connection.execute(
                    purge.batch_end, {"after": after, "offset": self._batch_rows - 1}
                )
                row = await cursor.fetchone()
                if row is None:
                    cursor = await connection.execute(purge.delete_rest, {"after": after})
                    return deleted + cursor.rowcount
                until = row[purge.column]
                cursor = await connection.execute(
                    purge.delete_batch, {"after": after, "until": until}
                )
                deleted += cursor.rowcount
            after = until

    async def run_every(self, interval_seconds: float = PURGE_INTERVAL_SECONDS) -> None:
        """Purge now, then again after every interval, until the task is cancelled."""
        while True:
            # A failed purge (the database restarting, for example) must not end the task:
            # the next one deletes what this one left.
            try:
                deleted = await self.run_once()
            except Exception:
                logger.exception(
                    "Deleting expired rows failed; trying again in %ss", interval_seconds
                )
            else:
                if any(deleted.values()):
                    logger.info("Deleted expired rows: %s", deleted)
            await asyncio.sleep(interval_seconds)
