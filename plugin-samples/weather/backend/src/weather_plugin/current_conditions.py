"""The current temperature of saved places, from Open-Meteo's forecast API, through the egress proxy.

`GET /api/places` lists each place with its temperature as Weather last looked it up. While it
answers, it looks up again every temperature that is missing or older than 15 minutes, for at
most 10 places per request, all at once, each within 5 seconds, and stores what it got. A lookup
that fails keeps the stored temperature, or none, and never fails the list. `observed_at` is
when Weather looked the temperature up.

`api.open-meteo.com` is the second host the manifest's `outbound_hosts` lists. Like the place
search (`weather_plugin.place_search`), the client reads the egress proxy from the environment.
"""

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from weather_plugin.places import PlaceConditions, SavedPlace, SavedPlaces, TemperatureCelsius

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
CONDITIONS_MAX_AGE = timedelta(minutes=15)
MAX_LOOKUPS_PER_REQUEST = 10
LOOKUP_TIMEOUT_SECONDS = 5

logger = logging.getLogger(__name__)


class TemperatureUnavailable(Exception):  # noqa: N818 (named like LookupFailed)
    """The proxy refused the call, or the forecast API failed or answered something else."""


class _Current(BaseModel):
    # The API answers more fields than this one.
    model_config = ConfigDict(frozen=True)

    temperature_2m: TemperatureCelsius


class _ForecastAnswer(BaseModel):
    model_config = ConfigDict(frozen=True)

    current: _Current


class CurrentTemperature:
    """Looks up the current temperature at a place. One instance per process: it holds a connection pool."""

    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None):
        # trust_env (httpx's default) reads the egress proxy from the environment. A
        # `transport` replaces the network, and the proxy with it, in tests.
        self._http = httpx.AsyncClient(
            transport=transport,
            trust_env=True,
            follow_redirects=False,
            timeout=LOOKUP_TIMEOUT_SECONDS,
        )

    async def at(self, latitude: float, longitude: float) -> float:
        """Return the current temperature at the coordinates, in degrees Celsius.

        Raises:
            TemperatureUnavailable: The proxy refused the call, the API could not be reached
                in time or answered with an error, or its answer has an unexpected shape.
        """
        try:
            response = await self._http.get(
                FORECAST_URL,
                params={"latitude": latitude, "longitude": longitude, "current": "temperature_2m"},
            )
        except httpx.HTTPError as error:
            # The class only: an error's text could carry the proxy's address.
            logger.warning("Temperature lookup failed: %s", type(error).__name__)
            raise TemperatureUnavailable from None
        if response.status_code != 200:
            logger.warning(
                "Temperature lookup failed: the forecast API answered %s", response.status_code
            )
            raise TemperatureUnavailable
        try:
            answer = _ForecastAnswer.model_validate_json(response.content)
        except ValidationError:
            logger.warning("Temperature lookup failed: the forecast API's answer has another shape")
            raise TemperatureUnavailable from None
        return answer.current.temperature_2m

    async def aclose(self) -> None:
        await self._http.aclose()


class PlacesWithConditions:
    """An organization's saved places, with temperatures no older than 15 minutes where it can."""

    def __init__(
        self,
        places: SavedPlaces,
        temperature: CurrentTemperature,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        self._places = places
        self._temperature = temperature
        self._clock = clock

    async def list(self, org_id: int) -> list[SavedPlace]:
        """Return the organization's places in position order, looking stale temperatures up first.

        The places with no temperature come first, then the oldest, then by position; only the
        first 10 of them are looked up. Places a lookup failed for keep what they had.
        """
        places = await self._places.list(org_id)
        now = self._clock()
        stale = sorted(
            (
                place
                for place in places
                if place.conditions is None
                or now - place.conditions.observed_at > CONDITIONS_MAX_AGE
            ),
            key=lambda place: (
                place.conditions is not None,
                place.conditions.observed_at if place.conditions else now,
                place.position,
            ),
        )[:MAX_LOOKUPS_PER_REQUEST]
        if not stale:
            return places
        temperatures = await asyncio.gather(*(self._lookup(place) for place in stale))
        fresh = {
            place.id: PlaceConditions(temperature_c=temperature, observed_at=now)
            for place, temperature in zip(stale, temperatures, strict=True)
            if temperature is not None
        }
        if fresh:
            await self._places.store_conditions(org_id, fresh)
        return [
            place.model_copy(update={"conditions": fresh[place.id]}) if place.id in fresh else place
            for place in places
        ]

    async def _lookup(self, place: SavedPlace) -> float | None:
        try:
            return await self._temperature.at(place.latitude, place.longitude)
        except TemperatureUnavailable:
            return None
