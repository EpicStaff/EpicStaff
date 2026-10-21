"""Deleting what Weather keeps only for a while: forecast runs after 7 days, expired popup results.

Requests never delete old rows. Once an hour, while the backend runs, `RetentionPurge` deletes
them for every organization at once, as the plugin's job role
(`WeatherDatabase.job_transaction`). The rule for what is old is in the job role's policies
(`database/migrations/002_retention.sql`), so these statements cannot reach a live row.

The purge goes in batches of about `PURGE_BATCH_ROWS` rows, oldest first along the timestamp
index, each batch in a transaction of its own. A batch stays well inside the database's
statement timeout however much has piled up, and holds its locks only briefly. Rows sharing the
timestamp a batch ends at go with that batch, so a batch can be a little larger.
"""

import asyncio
import logging

from weather_plugin.database import WeatherDatabase

PURGE_INTERVAL_SECONDS = 3600
PURGE_BATCH_ROWS = 5000

# Each deletes the expired rows up to the timestamp of the batch's last row; with fewer rows
# left than a batch, all of them ('infinity'). The policies limit both the subquery and the
# delete to expired rows.
PURGE_STATEMENTS = {
    "weather.forecast_runs": (
        "DELETE FROM weather.forecast_runs WHERE created_at <= COALESCE("
        "(SELECT created_at FROM weather.forecast_runs ORDER BY created_at OFFSET %s LIMIT 1),"
        " 'infinity')"
    ),
    "weather.popup_results": (
        "DELETE FROM weather.popup_results WHERE expires_at <= COALESCE("
        "(SELECT expires_at FROM weather.popup_results ORDER BY expires_at OFFSET %s LIMIT 1),"
        " 'infinity')"
    ),
}

logger = logging.getLogger(__name__)


class RetentionPurge:
    """Deletes expired rows of every organization."""

    def __init__(self, database: WeatherDatabase, *, batch_rows: int = PURGE_BATCH_ROWS):
        self._database = database
        self._batch_rows = batch_rows

    async def run_once(self) -> dict[str, int]:
        """Delete every expired row now, in batches, and return how many went from each table."""
        deleted = {}
        for table, statement in PURGE_STATEMENTS.items():
            deleted[table] = 0
            while True:
                async with self._database.job_transaction() as connection:
                    cursor = await connection.execute(statement, (self._batch_rows - 1,))
                deleted[table] += cursor.rowcount
                if cursor.rowcount < self._batch_rows:
                    break
        return deleted

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
