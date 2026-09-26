from typing import Any, Literal

import httpx
from loguru import logger

from clients.errors import (
    ClientBadGatewayError,
    ClientNotAvailableError,
    ClientTimeoutError,
    ClientValidationError,
)

Operation = Literal["read", "write", "delete"]


class PersistenceClient:
    """Async client for Django's session-scoped internal persistence route."""

    def __init__(
        self,
        base_url: str,
        api_key: str | None,
        timeout: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url
        self._api_key = api_key
        self._timeout = timeout
        self._transport = transport
        self._client: httpx.AsyncClient | None = None

    async def start(self) -> None:
        if self._client is None:
            # Same Host override realtime uses, so Django's ALLOWED_HOSTS accepts the call.
            headers = {"Host": "localhost"}
            # DJANGO_API_KEY is optional in local dev: crew must still start without it, and
            # only persistence calls fail (see _post).
            if self._api_key:
                headers["X-API-Key"] = self._api_key
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout,
                transport=self._transport,
                headers=headers,
            )
            logger.info("PersistenceClient started, base_url={}", self._base_url)

    async def stop(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
            logger.info("PersistenceClient stopped")

    async def read(self, session_id: int, table_id: int, keys: list[str]) -> dict[str, Any]:
        """Return `{"values": {key: value}, "table_name": str}`; missing keys are absent."""
        return await self._post(session_id, table_id, "read", {"keys": keys})

    async def write(
        self, session_id: int, table_id: int, entries: dict[str, Any]
    ) -> dict[str, Any]:
        """Return `{"written": int, "created": [new keys], "table_name": str}`."""
        return await self._post(session_id, table_id, "write", {"entries": entries})

    async def delete(self, session_id: int, table_id: int, keys: list[str]) -> dict[str, Any]:
        """Return `{"deleted": int, "table_name": str}`."""
        return await self._post(session_id, table_id, "delete", {"keys": keys})

    async def _post(
        self, session_id: int, table_id: int, operation: Operation, payload: dict
    ) -> dict:
        assert self._client is not None, "PersistenceClient.start() must be called first"
        if not self._api_key:
            raise ClientNotAvailableError(
                "DJANGO_API_KEY is not configured; persistence nodes can't reach Django."
            )
        url = f"internal/sessions/{session_id}/persistence-tables/{table_id}/{operation}/"
        try:
            response = await self._client.post(url, json=payload)
        except httpx.TimeoutException as e:
            raise ClientTimeoutError("Django persistence route timed out.") from e
        except httpx.RequestError as e:
            raise ClientNotAvailableError("Django persistence route is unreachable.") from e
        if response.status_code >= 500:
            raise ClientBadGatewayError(response.text)
        if response.status_code >= 400:
            raise ClientValidationError(self._error_message(response))
        return response.json()

    @staticmethod
    def _error_message(response: httpx.Response) -> str:
        try:
            return response.json().get("message", response.text)
        except ValueError:
            return response.text
