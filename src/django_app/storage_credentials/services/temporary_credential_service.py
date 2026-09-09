"""Mints/revokes one per-execution temporary MinIO service account.

Sync/async boundary: reading `Secret(system=True)` (via `OrgCredentialStore`)
is a sync Django ORM call. This runs inside the issuer's single event loop
(`run_storage_credential_issuer`), so the ORM read goes through
`asyncio.to_thread()` around the whole sync helper -- never `sync_to_async`
wrapping individual ORM calls scattered through async code.
"""

from dataclasses import dataclass
from datetime import timedelta

from storage_credentials.constants import TEMPORARY_CREDENTIAL_TTL_SECONDS_DEFAULT
from storage_credentials.policies import build_temporary_policy
from storage_credentials.services.org_credential_cache import org_credential_cache
from storage_credentials.services.scope_validator import credential_scope_validator


@dataclass(frozen=True)
class IssuedCredential:
    access_key: str
    secret_key: str


class TemporaryCredentialService:
    def __init__(self, *, host: str, bucket: str):
        self._host = host
        self._bucket = bucket

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
        _org_credentials, gateway = await org_credential_cache.get(
            org_id=org_id, host=self._host
        )
        policy = build_temporary_policy(
            bucket=self._bucket, allowed_folders=scoped_folders
        )
        ttl = timedelta(seconds=TEMPORARY_CREDENTIAL_TTL_SECONDS_DEFAULT)
        access_key, secret_key = await gateway.create_service_account(
            policy, expiration=ttl
        )
        return IssuedCredential(access_key=access_key, secret_key=secret_key)

    async def revoke(self, *, org_id: int, access_key: str) -> None:
        _org_credentials, gateway = await org_credential_cache.get(
            org_id=org_id, host=self._host
        )
        await gateway.delete_service_account(access_key)
