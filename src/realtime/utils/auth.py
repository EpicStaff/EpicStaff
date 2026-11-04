import httpx
from loguru import logger


class DjangoAuthClient:
    """Check websocket callers' tokens against Django's auth API without blocking the loop.

    One pooled `httpx.AsyncClient` serves every handshake. `start()` opens it and
    `stop()` closes it; the app calls them on FastAPI startup and shutdown.
    """

    def __init__(self, *, base_url: str, api_key: str, timeout: float, **httpx_options) -> None:
        self._base_url = base_url
        self._api_key = api_key
        self._timeout = timeout
        self._httpx_options = httpx_options
        self._http_client: httpx.AsyncClient | None = None
        self._api_key_validated = False

    async def start(self) -> None:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout,
                # Django rejects the compose service name as a Host; "localhost" is allowed.
                headers={"Host": "localhost", "X-API-Key": self._api_key},
                **self._httpx_options,
            )

    async def stop(self) -> None:
        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

    async def validate_api_key(self) -> bool:
        """Return whether Django accepts this service's API key; success is cached.

        Concurrent first calls each send a request; that is harmless, as each sets
        the same flag. They are not serialized behind a lock on purpose: with Django
        down, a lock would queue every handshake behind the previous one's timeout.
        """
        if self._api_key_validated:
            return True
        assert self._http_client is not None, "DjangoAuthClient.start() must be called first"
        try:
            response = await self._http_client.get("/api/auth/api-key/validate/")
        except httpx.HTTPError:
            logger.warning("API key validation request failed")
            return False

        if response.status_code != 200:
            logger.warning("API key validation failed with status {}", response.status_code)
            return False

        data = _json_object(response)
        if data is None:
            logger.warning("API key validation returned a body that is not a JSON object")
            return False

        if not data.get("active"):
            logger.warning("API key validation returned inactive")
            return False

        self._api_key_validated = True
        return True

    async def introspect_token(self, token: str) -> dict | None:
        """Return Django's introspection of an active user token, or None.

        None covers every refusal: an invalid service API key, an unreachable
        Django, a non-200 answer, a body that is not a JSON object and an
        inactive token.
        """
        if not await self.validate_api_key():
            return None
        assert self._http_client is not None, "DjangoAuthClient.start() must be called first"
        try:
            response = await self._http_client.post("/api/auth/introspect/", json={"token": token})
        except httpx.HTTPError:
            logger.warning("Token introspection request failed")
            return None

        if response.status_code != 200:
            logger.warning("Token introspection failed with status {}", response.status_code)
            return None

        data = _json_object(response)
        if data is None:
            logger.warning("Token introspection returned a body that is not a JSON object")
            return None

        if not data.get("active"):
            logger.warning("Token introspection returned inactive")
            return None
        return data


def _json_object(response: httpx.Response) -> dict | None:
    """Return the response body as a JSON object, or None if it is anything else."""
    try:
        data = response.json()
    except ValueError:
        return None
    return data if isinstance(data, dict) else None
