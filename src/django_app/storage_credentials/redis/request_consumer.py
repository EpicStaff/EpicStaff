"""Consumes per-execution MinIO credential requests from a durable Redis
Stream + consumer group.

Why a Stream here and not List+BLPOP (used for the response channel) or a
GETDEL key (used for the scope): this is the one link in the flow where a
future horizontally-scaled issuer could otherwise double-process the same
request (two replicas both dequeue and both mint an account for the same
execution_id). A consumer group gives at-least-once delivery and
redelivery of abandoned (never-acked) messages via XAUTOCLAIM, which a
simple queue would not.
"""

import asyncio
import json
import os
import socket

import redis.asyncio as aioredis
from loguru import logger

from src.shared.redis_streams import RedisStreamClient, StreamEnvelope, StreamMessage

from storage_credentials.constants import (
    CREDENTIAL_RESPONSE_TTL_SECONDS,
    STORAGE_CREDENTIAL_REQUEST_CLAIM_MIN_IDLE_MS,
    STORAGE_CREDENTIAL_REQUEST_CONSUMER_GROUP,
    STORAGE_CREDENTIAL_REQUEST_STREAM,
    TEMPORARY_CREDENTIAL_TTL_SECONDS_MAX,
)
from storage_credentials.exceptions import (
    CredentialScopeValidationError,
    OrgStorageCredentialMissingError,
    TemporaryCredentialError,
)
from storage_credentials.redis import keys
from storage_credentials.services.temporary_credential_service import (
    IssuedCredential,
    TemporaryCredentialService,
)

# Derived once at import time from hostname + PID rather than hardcoded:
# there is a single active issuer process per deployment today, but the
# name must not collide with another instance of the same container (e.g.
# during a rolling restart) or go stale across process restarts.
_CONSUMER_NAME = f"issuer-{socket.gethostname()}-{os.getpid()}"


class StorageCredentialRequestConsumer:
    def __init__(
        self,
        *,
        stream_client: RedisStreamClient,
        redis_client: aioredis.Redis,
        credential_service: TemporaryCredentialService,
    ):
        self._stream_client = stream_client
        self._redis_client = redis_client
        self._credential_service = credential_service

    async def run_forever(self) -> None:
        await self._stream_client.ensure_group(
            STORAGE_CREDENTIAL_REQUEST_STREAM,
            STORAGE_CREDENTIAL_REQUEST_CONSUMER_GROUP,
            start_id="0",
        )
        while True:
            try:
                await self._reclaim_abandoned()
                messages = await self._stream_client.read(
                    streams={STORAGE_CREDENTIAL_REQUEST_STREAM: ">"},
                    group=STORAGE_CREDENTIAL_REQUEST_CONSUMER_GROUP,
                    consumer=_CONSUMER_NAME,
                    count=10,
                    block_ms=5000,
                )
                for message in messages:
                    await self._handle(message)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                logger.error("StorageCredentialRequestConsumer loop error: {}", error)
                await asyncio.sleep(1)

    async def _reclaim_abandoned(self) -> None:
        reclaimed = await self._stream_client.autoclaim(
            STORAGE_CREDENTIAL_REQUEST_STREAM,
            STORAGE_CREDENTIAL_REQUEST_CONSUMER_GROUP,
            _CONSUMER_NAME,
            min_idle_ms=STORAGE_CREDENTIAL_REQUEST_CLAIM_MIN_IDLE_MS,
        )
        for message in reclaimed:
            await self._handle(message)

    async def _handle(self, message: StreamMessage) -> None:
        try:
            envelope = StreamEnvelope.from_fields(message.fields)
            await self._issue_for(envelope.correlation_id)
        except Exception as error:
            logger.error("Failed to process credential request message: {}", error)
        finally:
            await self._stream_client.ack(
                message.stream,
                STORAGE_CREDENTIAL_REQUEST_CONSUMER_GROUP,
                message.message_id,
            )

    async def _issue_for(self, execution_id: str) -> None:
        scope_raw = await self._redis_client.getdel(keys.scope_key(execution_id))
        if scope_raw is None:
            await self._respond_error(execution_id, "scope_not_published")
            return

        scope = json.loads(scope_raw)
        try:
            issued = await self._credential_service.issue(
                org_id=scope["org_id"],
                storage_org_prefix=scope["storage_org_prefix"],
                storage_allowed_paths=scope.get("storage_allowed_paths"),
            )
        except (
            CredentialScopeValidationError,
            OrgStorageCredentialMissingError,
            TemporaryCredentialError,
        ) as error:
            await self._respond_error(execution_id, str(error))
            return

        # TTL matches the temporary credential's own max lifetime, not the
        # short response TTL: this key must still be present when
        # `code_results` arrives for a long-running execution, otherwise
        # revocation would silently no-op and the account would be picked
        # up only later, by TtlReconciliationService.sweep().
        await self._redis_client.set(
            keys.lease_key(execution_id),
            json.dumps({"org_id": scope["org_id"], "access_key": issued.access_key}),
            ex=TEMPORARY_CREDENTIAL_TTL_SECONDS_MAX,
        )
        await self._respond_success(execution_id, issued)

    async def _respond_success(
        self, execution_id: str, issued: IssuedCredential
    ) -> None:
        key = keys.response_key(execution_id)
        await self._redis_client.rpush(
            key,
            json.dumps(
                {"access_key": issued.access_key, "secret_key": issued.secret_key}
            ),
        )
        await self._redis_client.expire(key, CREDENTIAL_RESPONSE_TTL_SECONDS)

    async def _respond_error(self, execution_id: str, error: str) -> None:
        key = keys.response_key(execution_id)
        await self._redis_client.rpush(key, json.dumps({"error": error}))
        await self._redis_client.expire(key, CREDENTIAL_RESPONSE_TTL_SECONDS)
