"""Process-wide TTL-60s cache of decrypted org-level MinIO credentials and
their `MinioAdminGateway`, shared by `TemporaryCredentialService` and
`TtlReconciliationService` -- both run inside the same long-lived event loop
(`run_storage_credential_issuer`).

Caching the gateway alongside its credentials -- rather than constructing a
fresh `MinioAdminGateway` on every `issue()`/`revoke()`/sweep() call -- avoids
leaking one aiohttp client session per call: `miniopy_async.MinioAdmin` opens
a session lazily and has no `close()`. The cached gateway is only rebuilt
(and the old one's session closed) when its credentials are refreshed on TTL
expiry, so it never keeps serving a stale org-level MinIO account past that
point.
"""

import asyncio
import time
from dataclasses import dataclass

from django.db import close_old_connections

from storage_credentials.clients.minio_admin_client import MinioAdminGateway
from storage_credentials.services.org_credential_store import (
    OrgMinioCredentials,
    org_credential_store,
)


def _get_org_credentials(org_id: int) -> OrgMinioCredentials:
    # Runs in a worker thread via `asyncio.to_thread()`, on the issuer's
    # single, long-lived event loop -- that thread's DB connection can go
    # stale (e.g. across a Postgres restart/failover) and every subsequent
    # ORM call from it then fails with InterfaceError forever, unless the
    # stale connection is discarded first. Matches the established pattern
    # in `tables/services/redis_pubsub.py`.
    close_old_connections()
    return org_credential_store.get(org_id=org_id)


@dataclass(frozen=True)
class _CacheEntry:
    cached_at: float
    credentials: OrgMinioCredentials
    gateway: MinioAdminGateway


class OrgCredentialCache:
    _TTL_SECONDS = 60

    def __init__(self):
        self._entries: dict[int, _CacheEntry] = {}

    async def get(
        self, *, org_id: int, host: str
    ) -> tuple[OrgMinioCredentials, MinioAdminGateway]:
        now = time.monotonic()
        cached = self._entries.get(org_id)
        if cached is not None and now - cached.cached_at < self._TTL_SECONDS:
            return cached.credentials, cached.gateway

        credentials = await asyncio.to_thread(_get_org_credentials, org_id)
        gateway = MinioAdminGateway(
            host=host,
            access_key=credentials.access_key,
            secret_key=credentials.secret_key,
        )
        self._entries[org_id] = _CacheEntry(
            cached_at=now, credentials=credentials, gateway=gateway
        )

        if cached is not None:
            await cached.gateway.close()

        return credentials, gateway


org_credential_cache = OrgCredentialCache()
