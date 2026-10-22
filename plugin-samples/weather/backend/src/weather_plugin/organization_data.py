"""Everything Weather keeps for an organization, deleted together when the organization leaves.

The organization removed hook (`weather_plugin.app`) calls `OrganizationData.delete`. One
transaction for that organization deletes its rows from every Weather table: row-level security
already limits each statement to the organization, and each also says `WHERE org_id`, so the
delete stays right if a policy ever changes. Running it again deletes nothing more.

A new table with organization rows gets its statement here; a test compares these statements
with the tables the migrations create. A table whose rows go with another table's comes first:
the cascade would delete them too, but uncounted.
"""

from weather_plugin.database import WeatherDatabase

DELETE_ORGANIZATION_ROWS = (
    "DELETE FROM weather.place_conditions WHERE org_id = %s",
    "DELETE FROM weather.saved_places WHERE org_id = %s",
    "DELETE FROM weather.forecast_runs WHERE org_id = %s",
    "DELETE FROM weather.popup_results WHERE org_id = %s",
)


class OrganizationData:
    """Weather's data for each organization, as a whole."""

    def __init__(self, database: WeatherDatabase):
        self._database = database

    async def delete(self, org_id: int) -> int:
        """Delete every row Weather keeps for the organization, and return how many there were."""
        deleted = 0
        async with self._database.transaction(org_id) as connection:
            for statement in DELETE_ORGANIZATION_ROWS:
                cursor = await connection.execute(statement, (org_id,))
                deleted += cursor.rowcount
        return deleted
