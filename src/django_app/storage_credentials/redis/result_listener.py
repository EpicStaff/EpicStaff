"""Revokes a temporary service account, triggered by the same `code_results`
message every code-execution consumer already sees -- no second transport
for this event.

`GETDEL` on the lease key makes revocation execute-once per execution_id:
a duplicate `code_results` delivery finds the lease already gone and is a
silent no-op, rather than a second `delete_service_account` call against an
account that's already gone.
"""

import asyncio
import json

import redis.asyncio as aioredis
from loguru import logger

from storage_credentials.constants import CODE_RESULTS_CHANNEL
from storage_credentials.redis import keys
from storage_credentials.services.temporary_credential_service import (
    TemporaryCredentialService,
)


class StorageCredentialResultListener:
    def __init__(
        self,
        *,
        redis_client: aioredis.Redis,
        credential_service: TemporaryCredentialService,
        channel: str = CODE_RESULTS_CHANNEL,
    ):
        self._redis_client = redis_client
        self._credential_service = credential_service
        self._channel = channel

    async def run_forever(self) -> None:
        while True:
            try:
                pubsub = self._redis_client.pubsub()
                await pubsub.subscribe(self._channel)
                async for message in pubsub.listen():
                    if message["type"] != "message":
                        continue
                    await self._handle(message["data"])
            except asyncio.CancelledError:
                raise
            except Exception as error:
                logger.error(
                    "StorageCredentialResultListener disconnected, "
                    "reconnecting in 1s: {}",
                    error,
                )
                await asyncio.sleep(1)

    async def _handle(self, raw: str) -> None:
        try:
            execution_id = json.loads(raw)["execution_id"]
        except Exception:
            return

        lease_raw = await self._redis_client.getdel(keys.lease_key(execution_id))
        if lease_raw is None:
            return

        lease = json.loads(lease_raw)
        try:
            await self._credential_service.revoke(
                org_id=lease["org_id"], access_key=lease["access_key"]
            )
        except Exception as error:
            logger.error(
                "Failed to revoke temporary credential for execution_id={}: {}",
                execution_id,
                error,
            )
