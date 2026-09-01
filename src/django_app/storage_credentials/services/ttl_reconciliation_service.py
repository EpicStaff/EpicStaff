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

from loguru import logger

from tables.models import Secret

from storage_credentials.clients.minio_admin_client import MinioAdminGateway
from storage_credentials.constants import SECRET_NAME_ORG_MINIO_USER
from storage_credentials.services.org_credential_store import (
    OrgMinioCredentials,
    org_credential_store,
)


def _list_provisioned_org_ids() -> list[int]:
    return list(
        Secret.objects.filter(name=SECRET_NAME_ORG_MINIO_USER, system=True)
        .exclude(metadata__revoked=True)
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
        org_credentials: OrgMinioCredentials = await asyncio.to_thread(
            org_credential_store.get, org_id=org_id
        )
        gateway = MinioAdminGateway(
            host=self._host,
            access_key=org_credentials.access_key,
            secret_key=org_credentials.secret_key,
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
