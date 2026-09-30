"""Safety net for temporary service accounts whose revocation signal
(`code_results`) was lost -- crashed sandbox, dropped Redis message, etc.

Independent of the GETDEL-based lease/execute-once revocation in
`run_storage_credential_issuer`'s result listener: this reads the storage backend's own
`expiration` timestamp on each active service account, via
`StorageAdminGateway.list_service_accounts()`, and revokes (`delete_service_account`)
anything past it. No in-memory or Redis state of its own, so it recovers
even across an issuer restart.
"""

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime

from django.db import close_old_connections
from loguru import logger
from tables.models import Secret

from storage_credentials.constants import SECRET_NAME_ORG_STORAGE_USER
from storage_credentials.services.org_credential_cache import org_credential_cache


@dataclass
class SweepStatistics:
    """Track sweep results for visibility and monitoring."""

    total_organizations: int
    organizations_processed: int
    organizations_failed: int
    total_accounts_checked: int
    total_accounts_revoked: int
    total_revocation_failures: int


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
        Secret.all_objects.filter(name=SECRET_NAME_ORG_STORAGE_USER, system=True)
        .exclude(metadata__contains={"revoked": True})
        .values_list("org_id", flat=True)
    )


def _parse_expiration(raw: str) -> datetime | None:
    """Parse ISO-8601 expiration timestamp from storage backend response."""
    try:
        return datetime.strptime(raw, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except (TypeError, ValueError):
        return None


class TtlReconciliationService:
    def __init__(self, *, host: str):
        self._host = host

    async def sweep(self) -> None:
        """Execute TTL reconciliation sweep across all provisioned organizations.

        Reads service account expiration timestamps from the storage backend
        (RustFS or MinIO) and revokes any that are past their TTL. Failures
        in one organization do not prevent sweeping other organizations.
        """
        org_ids = await asyncio.to_thread(_list_provisioned_org_ids)
        stats = SweepStatistics(
            total_organizations=len(org_ids),
            organizations_processed=0,
            organizations_failed=0,
            total_accounts_checked=0,
            total_accounts_revoked=0,
            total_revocation_failures=0,
        )

        for org_id in org_ids:
            try:
                org_stats = await self._sweep_one_org(org_id)
                stats.organizations_processed += 1
                stats.total_accounts_checked += org_stats["accounts_checked"]
                stats.total_accounts_revoked += org_stats["accounts_revoked"]
                stats.total_revocation_failures += org_stats["revocation_failures"]
            except Exception as error:
                stats.organizations_failed += 1
                logger.error(
                    "TtlReconciliationService: sweep failed for org_id={}: {}",
                    org_id,
                    error,
                )

        # Log summary statistics for monitoring
        logger.info(
            "TtlReconciliationService sweep completed: "
            "organizations_processed={}/{} (failed={}), "
            "accounts_checked={}, revoked={}, revocation_failures={}",
            stats.organizations_processed,
            stats.total_organizations,
            stats.organizations_failed,
            stats.total_accounts_checked,
            stats.total_accounts_revoked,
            stats.total_revocation_failures,
        )

    async def _sweep_one_org(self, org_id: int) -> dict:
        """Sweep and revoke expired service accounts for a single organization.

        Returns a dict with:
        - accounts_checked: number of accounts examined
        - accounts_revoked: number successfully revoked
        - revocation_failures: number that failed to revoke
        """
        org_credentials, gateway = await org_credential_cache.get(org_id=org_id, host=self._host)
        accounts = await gateway.list_service_accounts(org_credentials.access_key)
        now = datetime.now(UTC)

        accounts_checked = 0
        accounts_revoked = 0
        revocation_failures = 0

        for account in accounts:
            access_key = account.get("accessKey")
            expiration = _parse_expiration(account.get("expiration", ""))

            accounts_checked += 1

            # Skip invalid or non-expired accounts
            if not access_key or expiration is None or expiration > now:
                continue

            try:
                await gateway.delete_service_account(access_key)
                accounts_revoked += 1
                logger.info(
                    "TtlReconciliationService: revoked expired service account "
                    "access_key={} (org_id={}, expired_at={})",
                    access_key,
                    org_id,
                    expiration.isoformat(),
                )
            except Exception as error:
                revocation_failures += 1
                logger.error(
                    "TtlReconciliationService: failed to revoke expired service "
                    "account access_key={} (org_id={}, expired_at={}): {}",
                    access_key,
                    org_id,
                    expiration.isoformat(),
                    error,
                )

        return {
            "accounts_checked": accounts_checked,
            "accounts_revoked": accounts_revoked,
            "revocation_failures": revocation_failures,
        }
