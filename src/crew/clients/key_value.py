import asyncio
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

# Django's app server closes a keep-alive connection after 2 s idle (gunicorn's --keep-alive
# default, which UvicornWorker applies). Ours must expire first: a request sent on a connection
# the server is closing at that moment is reset and surfaces as httpx.ReadError.
KEEPALIVE_EXPIRY_SECONDS = 1.0
# Wait before each retry of a call whose connection failed; a call gets one attempt more than
# there are waits.
RETRY_BACKOFF_SECONDS = (0.2, 0.4, 0.8)
# Django either never received the request or dropped it with the connection. Timeouts are not
# here: after a ReadTimeout, Django may still be running the request.
_RETRYABLE_ERRORS = (httpx.NetworkError, httpx.RemoteProtocolError)


class KeyValueClient:
    """Async client for Django's session-scoped internal key-value route."""

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
            # only key-value calls fail (see _post).
            if self._api_key:
                headers["X-API-Key"] = self._api_key
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout,
                transport=self._transport,
                headers=headers,
                limits=httpx.Limits(
                    max_connections=100,
                    max_keepalive_connections=20,
                    keepalive_expiry=KEEPALIVE_EXPIRY_SECONDS,
                ),
            )
            logger.info("KeyValueClient started, base_url={}", self._base_url)

    async def stop(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
            logger.info("KeyValueClient stopped")

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
        assert self._client is not None, "KeyValueClient.start() must be called first"
        if not self._api_key:
            raise ClientNotAvailableError(
                "DJANGO_API_KEY is not configured; Key-Value nodes can't reach Django."
            )
        url = f"internal/sessions/{session_id}/key-value-tables/{table_id}/{operation}/"
        try:
            response = await self._send(url, payload)
        except httpx.TimeoutException as e:
            raise ClientTimeoutError("Django did not respond in time.") from e
        except httpx.RequestError as e:
            raise ClientNotAvailableError("Django is unreachable.") from e
        if response.status_code >= 500:
            raise ClientBadGatewayError(response.text)
        if response.status_code >= 400:
            raise ClientValidationError(self._error_message(response))
        return response.json()

    async def _send(self, url: str, payload: dict) -> httpx.Response:
        """POST, retrying _RETRYABLE_ERRORS after each RETRY_BACKOFF_SECONDS wait.

        Every operation is safe to replay: write upserts by key and delete removes by key, so
        a retry after an attempt that committed leaves the same rows. Only the reported
        `created` keys and `deleted` count can come back low on such a retry. The last
        attempt's error, and any timeout, propagate unchanged.
        """
        assert self._client is not None
        for attempt, wait in enumerate(RETRY_BACKOFF_SECONDS, start=1):
            try:
                return await self._client.post(url, json=payload)
            except _RETRYABLE_ERRORS as e:
                # The path names the session, table and operation; it carries no secrets.
                logger.warning(
                    "Key-Value call {} attempt {} failed with {}; retrying in {}s",
                    url,
                    attempt,
                    type(e).__name__,
                    wait,
                )
                await asyncio.sleep(wait)
        return await self._client.post(url, json=payload)

    @staticmethod
    def _error_message(response: httpx.Response) -> str:
        try:
            return response.json().get("message", response.text)
        except ValueError:
            return response.text
