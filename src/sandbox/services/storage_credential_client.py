"""Requests a per-execution temporary MinIO credential from the issuer
process running in `django_app`, and waits for its response.

`sandbox` never mints or revokes anything itself anymore, and never claims
its own `org_id`/`storage_org_prefix` -- it only ever asks for credentials
by `execution_id`. The trusted scope for that `execution_id` is written by
whichever publisher (`crew`, `agent`, `realtime`, django "Test run")
created the task, before it reached `code_exec_tasks`.

Response transport is a Redis List + BLPOP, not Pub/Sub: unlike a Pub/Sub
message published with no subscriber listening (lost forever), a value
RPUSHed to a list key persists there until something BLPOPs it, so this
does not have Pub/Sub's "publish arrived before subscribe" failure mode.
We still enter the BLPOP wait before sending the request (rather than
after) as defense in depth and to keep the code visibly consistent with
that same ordering principle used on the Pub/Sub-based request channel.
"""

import asyncio
import json

import redis.asyncio as aioredis
from loguru import logger

from src.shared.redis_streams import RedisStreamClient, StreamEnvelope

STORAGE_CREDENTIAL_REQUEST_STREAM = "storage_credential_requests"
STORAGE_CREDENTIAL_REQUEST_ENVELOPE_TYPE = "issue_temporary_credential"
STORAGE_CREDENTIAL_WAIT_TIMEOUT_S = 15


class StorageCredentialRequestError(Exception):
    """Sandbox fails closed on any of these: no code execution proceeds
    without a successfully issued temporary credential."""


class StorageCredentialClient:
    def __init__(
        self,
        *,
        host: str,
        port: int,
        password: str | None,
        stream_client: RedisStreamClient,
    ):
        self._host = host
        self._port = port
        self._password = password
        self._stream_client = stream_client

    async def request(self, execution_id: str) -> dict[str, str]:
        """Returns `{"access_key": ..., "secret_key": ...}` or raises
        `StorageCredentialRequestError` (timeout, issuer-reported error, or
        malformed response) -- callers must treat any of those as fail-closed."""
        response_key = f"storage_credential_response:{execution_id}"
        wait_task = asyncio.create_task(self._blpop(response_key))

        try:
            await self._publish_request(execution_id)

            try:
                raw = await asyncio.wait_for(
                    wait_task, timeout=STORAGE_CREDENTIAL_WAIT_TIMEOUT_S
                )
            except asyncio.TimeoutError as error:
                raise StorageCredentialRequestError(
                    f"Timed out waiting for storage credentials "
                    f"(execution_id={execution_id})"
                ) from error
        finally:
            if not wait_task.done():
                wait_task.cancel()

        if raw is None:
            raise StorageCredentialRequestError(
                f"No storage credential response received (execution_id={execution_id})"
            )

        try:
            payload = json.loads(raw)
        except (TypeError, ValueError) as error:
            raise StorageCredentialRequestError(
                f"Malformed storage credential response: {error}"
            ) from error

        if "error" in payload:
            raise StorageCredentialRequestError(str(payload["error"]))

        if "access_key" not in payload or "secret_key" not in payload:
            raise StorageCredentialRequestError(
                "Storage credential response is missing access_key/secret_key."
            )

        return payload

    async def _blpop(self, response_key: str) -> str | None:
        client = aioredis.Redis(
            host=self._host,
            port=self._port,
            password=self._password,
            decode_responses=True,
        )
        try:
            result = await client.blpop(
                response_key, timeout=STORAGE_CREDENTIAL_WAIT_TIMEOUT_S
            )
        finally:
            await client.aclose()
        if result is None:
            return None
        _key, value = result
        return value

    async def _publish_request(self, execution_id: str) -> None:
        envelope = StreamEnvelope(
            type=STORAGE_CREDENTIAL_REQUEST_ENVELOPE_TYPE,
            correlation_id=execution_id,
            payload={},
        )
        try:
            await self._stream_client.publish(
                STORAGE_CREDENTIAL_REQUEST_STREAM, envelope.to_fields()
            )
        except Exception as error:
            logger.error(
                "Failed to publish storage credential request (execution_id={}): {}",
                execution_id,
                error,
            )
            raise
