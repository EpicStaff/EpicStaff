"""The places an organization saves, and their current temperatures, kept in Weather's database.

Every query runs in one organization's transaction, and the tables' row-level security does
the rest: a list shows only that organization's places, and removing another organization's
place finds nothing, without a `WHERE org_id` in the SQL.

A list is in the order the places were saved (`position`). Each place carries its temperature
as Weather last looked it up (`weather.place_conditions`), or none; looking temperatures up is
`weather_plugin.current_conditions`'s job.
"""

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Annotated, Any

from pydantic import AfterValidator, AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints

from weather_plugin.database import WeatherDatabase

# The longest place name Weather keeps. A forecast takes any saved place's name, so its city
# field has the same limit.
MAX_PLACE_NAME_LENGTH = 200

PlaceName = Annotated[str, StringConstraints(min_length=1, max_length=MAX_PLACE_NAME_LENGTH)]
CountryName = Annotated[str, StringConstraints(min_length=1, max_length=100)]
RegionName = Annotated[str, StringConstraints(max_length=200)]
Latitude = Annotated[float, Field(ge=-90, le=90)]
Longitude = Annotated[float, Field(ge=-180, le=180)]


def _tenths(temperature: float) -> float:
    return round(temperature, 1)


def _in_utc(moment: datetime) -> datetime:
    return moment.astimezone(UTC)


# In tenths of a degree, as `numeric(5,1)` keeps it, so a value looked up now reads the same as
# the one stored from it. Every temperature on Earth fits with room to spare.
TemperatureCelsius = Annotated[
    float, Field(ge=-100, le=100, allow_inf_nan=False), AfterValidator(_tenths)
]


# Sent as ISO 8601 in UTC (`...Z`), whatever time zone the database session uses.
UtcDatetime = Annotated[AwareDatetime, AfterValidator(_in_utc)]


class PlaceCandidate(BaseModel):
    """A place a search found, and the body of `POST /api/places`."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    name: PlaceName
    country: CountryName
    admin1: RegionName | None = None
    """The region within the country, when the search knows one."""

    latitude: Latitude
    longitude: Longitude


class PlaceConditions(BaseModel):
    """A place's current temperature, and when Weather looked it up."""

    model_config = ConfigDict(frozen=True)

    # A float, so the answer carries a JSON number: the database gives a Decimal, which
    # pydantic would send as a string.
    temperature_c: TemperatureCelsius
    observed_at: UtcDatetime


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
    position: int
    """Where the place is in its organization's list: 1 for the first one saved."""

    conditions: PlaceConditions | None = None
    """Its temperature as Weather last looked it up; None until a lookup succeeds."""


class AlreadySaved(Exception):  # noqa: N818 (named after the route's answer code)
    """The organization already saved a place with this name, region and country."""


_COLUMNS = "id, name, admin1, country, latitude, longitude, created_at, position"
_PLACE_COLUMNS = ", ".join(f"place.{column}" for column in _COLUMNS.split(", "))

# Each place with its temperature, if it has one. Row-level security limits both tables to the
# organization; joining on org_id as well uses place_conditions' primary key.
_LIST = (
    f"SELECT {_PLACE_COLUMNS}, conditions.temperature_c, conditions.observed_at"
    " FROM weather.saved_places AS place"
    " LEFT JOIN weather.place_conditions AS conditions"
    " ON conditions.org_id = place.org_id AND conditions.place_id = place.id"
    " ORDER BY place.position, place.id"
)

# The organization's highest position plus one. The advisory lock in the same transaction
# (`POSITION_LOCK`, keyed by the organization) makes two adds in one organization take turns,
# so they never read the same highest position. That holds under read committed, the
# connections' isolation: each statement reads a fresh snapshot, taken after the lock was
# granted. Under repeatable read the transaction's snapshot would predate the lock, and two
# adds could still read the same highest position.
_ADD = (
    "INSERT INTO weather.saved_places"
    " (org_id, name, admin1, country, latitude, longitude, created_by, position)"
    " SELECT %s, %s, %s, %s, %s, %s, %s, COALESCE(max(position), 0) + 1"
    " FROM weather.saved_places"
    " ON CONFLICT (org_id, name, admin1, country) DO NOTHING"
    f" RETURNING {_COLUMNS}"
)

# Namespaced, so the key never collides with another advisory lock of this database's roles.
# Public: the sample's tests take the same lock.
POSITION_LOCK = (
    "SELECT pg_advisory_xact_lock(hashtextextended('weather.saved_places.position', %s::bigint))"
)

# Writes each temperature for its place, if the place is still there. FOR KEY SHARE waits for
# a removal in progress and then skips the removed place, instead of failing on the foreign
# key; a removal that comes later takes the new row with the place.
_STORE_CONDITIONS = (
    "INSERT INTO weather.place_conditions (org_id, place_id, temperature_c, observed_at)"
    " SELECT place.org_id, place.id, fresh.temperature_c, fresh.observed_at"
    " FROM unnest(%s::bigint[], %s::numeric[], %s::timestamptz[])"
    " AS fresh (place_id, temperature_c, observed_at)"
    " JOIN weather.saved_places AS place ON place.id = fresh.place_id"
    " FOR KEY SHARE OF place"
    " ON CONFLICT (org_id, place_id) DO UPDATE"
    " SET temperature_c = EXCLUDED.temperature_c, observed_at = EXCLUDED.observed_at"
)


def _saved_place(row: Mapping[str, Any]) -> SavedPlace:
    place = {column: row[column] for column in _COLUMNS.split(", ")}
    if row.get("observed_at") is not None:
        place["conditions"] = {
            "temperature_c": row["temperature_c"],
            "observed_at": row["observed_at"],
        }
    return SavedPlace.model_validate(place)


class SavedPlaces:
    """The saved places of each organization, with their temperatures."""

    def __init__(self, database: WeatherDatabase):
        self._database = database

    async def list(self, org_id: int) -> list[SavedPlace]:
        """Return the organization's places in position order, each with its stored temperature."""
        async with self._database.transaction(org_id) as connection:
            cursor = await connection.execute(_LIST)
            return [_saved_place(row) for row in await cursor.fetchall()]

    async def add(self, org_id: int, user_id: int, place: PlaceCandidate) -> SavedPlace:
        """Save a place for the organization at the end of its list, recording who saved it.

        Raises:
            AlreadySaved: The organization has a place with this name, region and country.
        """
        async with self._database.transaction(org_id) as connection:
            await connection.execute(POSITION_LOCK, (org_id,))
            cursor = await connection.execute(
                _ADD,
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
        return _saved_place(row)

    async def remove(self, org_id: int, place_id: int) -> bool:
        """Remove one of the organization's places; False when it has none with this id."""
        async with self._database.transaction(org_id) as connection:
            cursor = await connection.execute(
                "DELETE FROM weather.saved_places WHERE id = %s", (place_id,)
            )
            return cursor.rowcount == 1

    async def store_conditions(
        self, org_id: int, conditions: Mapping[int, PlaceConditions]
    ) -> None:
        """Store each place's new temperature, by place id, in one statement.

        A place removed meanwhile is skipped, and so is an id the organization has no place
        with.
        """
        place_ids = list(conditions)
        async with self._database.transaction(org_id) as connection:
            await connection.execute(
                _STORE_CONDITIONS,
                (
                    place_ids,
                    [conditions[place_id].temperature_c for place_id in place_ids],
                    [conditions[place_id].observed_at for place_id in place_ids],
                ),
            )
