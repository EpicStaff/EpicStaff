"""Safety net for temporary service accounts whose revocation signal
(`code_results`) was lost -- crashed sandbox, dropped Redis message, etc.

Independent of the GETDEL-based lease/execute-once revocation in
`run_storage_credential_issuer`'s result listener: this reads MinIO's own
`expiration` timestamp on each active service account and revokes anything
past it, so it recovers even across an issuer restart with no in-memory or
Redis state of its own.
"""

import asyncio
from datetime import datetime, timezone

from django.db import close_old_connections
from loguru import logger

from tables.models import Secret

from storage_credentials.constants import SECRET_NAME_ORG_MINIO_USER
from storage_credentials.services.org_credential_cache import org_credential_cache


def _list_provisioned_org_ids() -> list[int]:
    # Runs in a worker thread via `asyncio.to_thread()` on the issuer's
    # single, long-lived event loop -- see `org_credential_cache._get_org_credentials`
    # for why `close_old_connections()` must run before every ORM call made
    # from that thread.
    close_old_connections()
    # `.exclude(metadata__contains={"revoked": True})` compiles to
    # `NOT (metadata @> '{"revoked": true}'::jsonb)`, which correctly
    # includes rows with `metadata={}` (a freshly-provisioned, never-revoked
    # row). `.exclude(metadata__revoked=True)` would instead compile to a
    # `NOT (... = true)` comparison against SQL NULL for such rows -- which
    # is itself NULL, not true -- silently dropping every unrevoked row from
    # the queryset. See org_credential_store.get()/exists() for the same
    # underlying JSON NULL semantics issue.
    return list(
        Secret.all_objects.filter(name=SECRET_NAME_ORG_MINIO_USER, system=True)
        .exclude(metadata__contains={"revoked": True})
        .values_list("org_id", flat=True)
    )


def _parse_expiration(raw: str) -> datetime | None:
    try:
        return datetime.strptime(raw, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


class TtlReconciliationService:
    def __init__(self, *, host: str):
        self._host = host

    async def sweep(self) -> None:
        org_ids = await asyncio.to_thread(_list_provisioned_org_ids)
        for org_id in org_ids:
            try:
                await self._sweep_one_org(org_id)
            except Exception as error:
                logger.error(
                    "TtlReconciliationService: sweep failed for org_id={}: {}",
                    org_id,
                    error,
                )

    async def _sweep_one_org(self, org_id: int) -> None:
        org_credentials, gateway = await org_credential_cache.get(
            org_id=org_id, host=self._host
        )
        accounts = await gateway.list_service_accounts(org_credentials.access_key)
        now = datetime.now(timezone.utc)

        for account in accounts:
            access_key = account.get("accessKey")
            expiration = _parse_expiration(account.get("expiration", ""))
            if not access_key or expiration is None or expiration > now:
                continue
            try:
                await gateway.delete_service_account(access_key)
                logger.info(
                    "TtlReconciliationService: revoked expired service account "
                    "access_key={} (org_id={})",
                    access_key,
                    org_id,
                )
            except Exception as error:
                logger.error(
                    "TtlReconciliationService: failed to revoke expired service "
                    "account access_key={} (org_id={}): {}",
                    access_key,
                    org_id,
                    error,
                )
