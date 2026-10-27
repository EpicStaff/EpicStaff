"""Finding places by name with Open-Meteo's geocoding API, through the egress proxy.

The backend reaches the internet only through the node's egress proxy, and only the hosts its
manifest lists under `outbound_hosts`: here `geocoding-api.open-meteo.com`. The node names the
proxy, with Weather's own credentials, in `HTTPS_PROXY` and keeps EpicStaff's API direct in
`NO_PROXY`; httpx reads both from the environment by default, so this client needs no proxy
setting of its own. (EpicStaff's client, `epicstaff_plugin.client`, never uses the proxy.)

The forecast itself is fetched by the flow's Python node inside EpicStaff, not by this backend.
"""

import logging

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from weather_plugin.places import (
    CountryName,
    Latitude,
    Longitude,
    PlaceCandidate,
    PlaceName,
    RegionName,
)

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
SEARCH_RESULT_COUNT = 5
SEARCH_TIMEOUT_SECONDS = 10
MAX_QUERY_LENGTH = 100

logger = logging.getLogger(__name__)


class LookupFailed(Exception):  # noqa: N818 (named after the route's answer code)
    """The proxy refused the call, or the geocoding API failed or answered something else."""


class _GeocodingResult(BaseModel):
    # The API answers more fields than these, and leaves out the ones it does not know.
    model_config = ConfigDict(frozen=True)

    name: PlaceName
    country: CountryName | None = None
    admin1: RegionName | None = None
    latitude: Latitude
    longitude: Longitude


class _GeocodingAnswer(BaseModel):
    model_config = ConfigDict(frozen=True)

    # Left out when nothing matches.
    results: list[_GeocodingResult] = Field(default_factory=list)


class PlaceSearch:
    """Looks places up by name. One instance per process: it holds a connection pool."""

    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None):
        # trust_env (httpx's default) reads the egress proxy from the environment. A
        # `transport` replaces the network, and the proxy with it, in tests.
        self._http = httpx.AsyncClient(
            transport=transport,
            trust_env=True,
            follow_redirects=False,
            timeout=SEARCH_TIMEOUT_SECONDS,
        )

    async def search(self, query: str) -> list[PlaceCandidate]:
        """Return up to five places whose name matches `query`; places without a country are left out.

        Raises:
            LookupFailed: The proxy refused the call, the API could not be reached or
                answered with an error, or its answer has an unexpected shape.
        """
        try:
            response = await self._http.get(
                GEOCODING_URL,
                params={"name": query, "count": SEARCH_RESULT_COUNT, "format": "json"},
            )
        except httpx.HTTPError as error:
            # The class only: an error's text could carry the proxy's address.
            logger.warning("Place search failed: %s", type(error).__name__)
            raise LookupFailed from None
        if response.status_code != 200:
            logger.warning(
                "Place search failed: the geocoding API answered %s", response.status_code
            )
            raise LookupFailed
        try:
            answer = _GeocodingAnswer.model_validate_json(response.content)
        except ValidationError:
            logger.warning("Place search failed: the geocoding API's answer has another shape")
            raise LookupFailed from None
        return [
            PlaceCandidate(
                name=result.name,
                country=result.country,
                admin1=result.admin1,
                latitude=result.latitude,
                longitude=result.longitude,
            )
            for result in answer.results
            if result.country is not None
        ]

    async def aclose(self) -> None:
        await self._http.aclose()
