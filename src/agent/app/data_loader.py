"""
Layer 6 helper — DataLoader: fetches and hydrates an ``AgentRequest`` from Redis K/V.

The Redis Streams message (``StreamEnvelope``) is a lightweight pointer.
The actual agent config, surface items, and task payload are stored in a
separate Redis K/V key carried inside the envelope.  ``DataLoader`` owns the
second Redis connection used exclusively for K/V reads; the main
``RedisStreamClient`` connection handles stream operations.
"""

from __future__ import annotations

import json

import redis.asyncio as aioredis
from loguru import logger

from app.exceptions import DataLoadError
from app.logging_utils import redacted_dump
from shared.models.agent_service import AgentRequest
from shared.redis_streams import StreamEnvelope


class DataLoader:
    """Fetches raw JSON from Redis K/V and deserialises it into an ``AgentRequest``.

    Maintains its own ``aioredis`` connection so that K/V reads are
    independent of the stream consumer connection in ``main.py``.
    ``connect()`` must be called before the first ``load()`` call;
    ``close()`` should be called on shutdown.
    """

    def __init__(self, host: str, port: int, password: str | None = None) -> None:
        self._host = host
        self._port = port
        self._password = password
        self._client: aioredis.Redis | None = None

    async def connect(self) -> None:
        """Open the Redis connection.  Must be called before ``load``."""
        url = f"redis://{self._host}:{self._port}"
        self._client = await aioredis.from_url(
            url,
            password=self._password,
            decode_responses=True,
        )
        logger.info("DataLoader connected to redis at {}:{}", self._host, self._port)

    async def close(self) -> None:
        """Close the Redis connection and release resources."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def load(self, envelope: StreamEnvelope) -> AgentRequest:
        """Fetch and parse the ``AgentRequest`` referenced by ``envelope``.

        Extracts the Redis key from the envelope payload, reads the JSON
        blob, and constructs a frozen ``AgentRequest``.

        Raises:
            DataLoadError: if the key is missing, the JSON is malformed,
                or the payload cannot be validated as an ``AgentRequest``.
        """
        assert self._client is not None, "call connect() first"

        request_key = self._extract_request_key(envelope)

        raw = await self._client.get(request_key)
        logger.debug(
            "loaded blob key={} bytes={}",
            request_key,
            len(raw) if raw is not None else 0,
        )

        if raw is None:
            raise DataLoadError(
                f"No data found at Redis key '{request_key}' "
                f"for correlation_id '{envelope.correlation_id}'"
            )

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as error:
            raise DataLoadError(
                f"Invalid JSON at Redis key '{request_key}': {error}"
            ) from error

        try:
            request = AgentRequest(
                correlation_id=envelope.correlation_id,
                **data,
            )
        except Exception as error:
            raise DataLoadError(
                f"Failed to parse AgentRequest from key '{request_key}': {error}"
            ) from error

        _corr_id = envelope.correlation_id
        logger.opt(lazy=True).debug(
            "AgentRequest correlation_id={} request={}",
            lambda: _corr_id,
            lambda: redacted_dump(request),
        )

        return request

    def _extract_request_key(self, envelope: StreamEnvelope) -> str:
        # PROVISIONAL: envelope payload must carry {"request_key": "agent:request:<id>"}
        return envelope.payload["request_key"]
