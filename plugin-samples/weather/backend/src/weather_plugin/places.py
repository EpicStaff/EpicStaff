"""The places an organization saves, kept in Weather's database.

Every query runs in one organization's transaction, and the table's row-level security does
the rest: a list shows only that organization's places, and removing another organization's
place finds nothing, without a `WHERE org_id` in the SQL.
"""

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from weather_plugin.database import WeatherDatabase

# The longest place name Weather keeps. A forecast takes any saved place's name, so its city
# field has the same limit.
MAX_PLACE_NAME_LENGTH = 200

PlaceName = Annotated[str, StringConstraints(min_length=1, max_length=MAX_PLACE_NAME_LENGTH)]
CountryName = Annotated[str, StringConstraints(min_length=1, max_length=100)]
RegionName = Annotated[str, StringConstraints(max_length=200)]
Latitude = Annotated[float, Field(ge=-90, le=90)]
Longitude = Annotated[float, Field(ge=-180, le=180)]


class PlaceCandidate(BaseModel):
    """A place a search found, and the body of `POST /api/places`."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    name: PlaceName
    country: CountryName
    admin1: RegionName | None = None
    """The region within the country, when the search knows one."""

    latitude: Latitude
    longitude: Longitude


class SavedPlace(BaseModel):
    """A place an organization saved, as `GET /api/places` lists it."""

    model_config = ConfigDict(frozen=True)

    id: int
    name: str
    admin1: str | None
    country: str
    latitude: float
    longitude: float
    created_at: datetime


class AlreadySaved(Exception):  # noqa: N818 (named after the route's answer code)
    """The organization already saved a place with this name, region and country."""


_COLUMNS = "id, name, admin1, country, latitude, longitude, created_at"


class SavedPlaces:
    """The saved places of each organization."""

    def __init__(self, database: WeatherDatabase):
        self._database = database

    async def list(self, org_id: int) -> list[SavedPlace]:
        """Return the organization's places, by name, country and region."""
        async with self._database.transaction(org_id) as connection:
            cursor = await connection.execute(
                f"SELECT {_COLUMNS} FROM weather.saved_places"
                " ORDER BY name, country, admin1 NULLS FIRST, id"
            )
            return [SavedPlace.model_validate(row) for row in await cursor.fetchall()]

    async def add(self, org_id: int, user_id: int, place: PlaceCandidate) -> SavedPlace:
        """Save a place for the organization, recording who saved it.

        Raises:
            AlreadySaved: The organization has a place with this name, region and country.
        """
        async with self._database.transaction(org_id) as connection:
            cursor = await connection.execute(
                "INSERT INTO weather.saved_places"
                " (org_id, name, admin1, country, latitude, longitude, created_by)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s)"
                " ON CONFLICT (org_id, name, admin1, country) DO NOTHING"
                f" RETURNING {_COLUMNS}",
                (
                    org_id,
                    place.name,
                    place.admin1,
                    place.country,
                    place.latitude,
                    place.longitude,
                    user_id,
                ),
            )
            row = await cursor.fetchone()
        if row is None:
            raise AlreadySaved
        return SavedPlace.model_validate(row)

    async def remove(self, org_id: int, place_id: int) -> bool:
        """Remove one of the organization's places; False when it has none with this id."""
        async with self._database.transaction(org_id) as connection:
            cursor = await connection.execute(
                "DELETE FROM weather.saved_places WHERE id = %s", (place_id,)
            )
            return cursor.rowcount == 1
