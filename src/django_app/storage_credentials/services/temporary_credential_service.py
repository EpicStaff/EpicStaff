"""Mints/revokes one per-execution temporary MinIO service account.

Sync/async boundary: reading `Secret(system=True)` (via `OrgCredentialStore`)
is a sync Django ORM call. This runs inside the issuer's single event loop
(`run_storage_credential_issuer`), so the ORM read goes through
`asyncio.to_thread()` around the whole sync helper -- never `sync_to_async`
wrapping individual ORM calls scattered through async code.
"""

import asyncio
import time
from dataclasses import dataclass
from datetime import timedelta

from storage_credentials.clients.minio_admin_client import MinioAdminGateway
from storage_credentials.constants import TEMPORARY_CREDENTIAL_TTL_SECONDS_DEFAULT
from storage_credentials.policies import build_temporary_policy
from storage_credentials.services.org_credential_store import (
    OrgMinioCredentials,
    org_credential_store,
)
from storage_credentials.services.scope_validator import credential_scope_validator


@dataclass(frozen=True)
class IssuedCredential:
    access_key: str
    secret_key: str


class _OrgCredentialCache:
    """In-process, TTL-60s cache of decrypted org-level MinIO credentials --
    avoids one ORM round trip (plus a Fernet decrypt) per issued execution
    when one org runs many executions in a short window."""

    _TTL_SECONDS = 60

    def __init__(self):
        self._entries: dict[int, tuple[float, OrgMinioCredentials]] = {}

    async def get(self, org_id: int) -> OrgMinioCredentials:
        now = time.monotonic()
        cached = self._entries.get(org_id)
        if cached is not None and now - cached[0] < self._TTL_SECONDS:
            return cached[1]
        credentials = await asyncio.to_thread(org_credential_store.get, org_id=org_id)
        self._entries[org_id] = (now, credentials)
        return credentials


class TemporaryCredentialService:
    def __init__(self, *, host: str, bucket: str):
        self._host = host
        self._bucket = bucket
        self._org_credentials_cache = _OrgCredentialCache()

    async def issue(
        self,
        *,
        org_id: int,
        storage_org_prefix: str,
        storage_allowed_paths: list[str] | None,
    ) -> IssuedCredential:
        scoped_folders = credential_scope_validator.validate(
            org_id=org_id,
            storage_org_prefix=storage_org_prefix,
            storage_allowed_paths=storage_allowed_paths,
        )
        org_credentials = await self._org_credentials_cache.get(org_id)
        gateway = self._build_gateway(org_credentials)
        policy = build_temporary_policy(
            bucket=self._bucket, allowed_folders=scoped_folders
        )
        ttl = timedelta(seconds=TEMPORARY_CREDENTIAL_TTL_SECONDS_DEFAULT)
        access_key, secret_key = await gateway.create_service_account(
            policy, expiration=ttl
        )
        return IssuedCredential(access_key=access_key, secret_key=secret_key)

    async def revoke(self, *, org_id: int, access_key: str) -> None:
        org_credentials = await self._org_credentials_cache.get(org_id)
        gateway = self._build_gateway(org_credentials)
        await gateway.delete_service_account(access_key)

    def _build_gateway(self, org_credentials: OrgMinioCredentials) -> MinioAdminGateway:
        return MinioAdminGateway(
            host=self._host,
            access_key=org_credentials.access_key,
            secret_key=org_credentials.secret_key,
        )
