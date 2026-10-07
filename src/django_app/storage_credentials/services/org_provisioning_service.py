"""Provisions and deprovisions the long-lived, org-level storage IAM user each
organization owns.

Sync/async boundary: `OrganizationManagementService.create_organization()`/
`deactivate_organization()` call in from inside `@transaction.atomic`;
`delete_organization()` calls in from a `transaction.on_commit()` callback,
i.e. synchronously but outside any transaction. `miniopy_async` (the only
storage Admin SDK available) is async-only. Per the project's async-I/O
convention, the two worlds are never interleaved inside one call: each public
method here reads nothing from the ORM itself, runs the entire storage
backend conversation through one `asyncio.run()`, and only then performs its
own sync ORM write (`OrgCredentialStore`/`Secret.objects...`) once the event
loop has exited.
"""

import asyncio
import secrets as secrets_module

from django.conf import settings
from loguru import logger
from rbac.models import Organization

from storage_credentials.clients.minio_admin_client import StorageAdminGateway
from storage_credentials.exceptions import OrgStorageProvisioningError
from storage_credentials.policies import build_org_user_policy
from storage_credentials.resource_names import _org_access_key, _org_policy_name, org_storage_prefix
from storage_credentials.services.org_credential_store import org_credential_store


class OrgStorageProvisioningService:
    def __init__(self):
        self._host = settings.STORAGE_ENDPOINT
        self._root_access_key = settings.STORAGE_ACCESS_KEY
        self._root_secret_key = settings.STORAGE_SECRET_KEY
        self._bucket = settings.STORAGE_BUCKET_NAME

    def provision_for_organization(self, org: Organization) -> None:
        """Create a new org-level storage IAM user scoped to `org_<id>/*`, and
        persist its credentials as `Secret(system=True)`. Called from inside
        `create_organization()`'s transaction; any failure here propagates
        so the whole organization-creation transaction rolls back -- an
        organization without provisioned storage is not a valid state.

        Also called from `reactivate_organization()`: `deactivate_organization()`
        removes the old storage user entirely (it cannot be un-removed), so
        reactivation always provisions a fresh one.
        """
        access_key = _org_access_key(org.id)
        secret_key = secrets_module.token_urlsafe(32)
        try:
            asyncio.run(
                self._provision_in_storage(
                    org_id=org.id, access_key=access_key, secret_key=secret_key
                )
            )
        except Exception as error:
            logger.exception(
                "Failed to provision storage user for org_id={}: {}",
                org.id,
                error,
            )
            raise OrgStorageProvisioningError() from error

        org_credential_store.save(org=org, access_key=access_key, secret_key=secret_key)
        logger.info("Provisioned org-level storage user for org_id={}", org.id)

    def deprovision_for_organization(self, org_id: int) -> None:
        """Remove the org-level storage user (cascades to revoke every active
        service account it minted) and delete the stored `Secret`.
        Objects already written under `org_<id>/*` are left untouched

        Takes `org_id` rather than an `Organization` instance: a delete-path
        caller only has the id left once the row itself is gone. In that case
        `delete()` is a safe no-op -- `Secret.org` cascades on org delete, so
        the row is already gone by the time this runs post-commit; only the
        storage-side removal still matters there."""
        access_key = _org_access_key(org_id)
        try:
            asyncio.run(self._deprovision_in_storage(org_id=org_id, access_key=access_key))
        except Exception as error:
            logger.exception(
                "Failed to deprovision storage user for org_id={}: {}",
                org_id,
                error,
            )
            raise OrgStorageProvisioningError() from error

        org_credential_store.delete(org_id=org_id)
        logger.info("Deprovisioned org-level storage user for org_id={}", org_id)

    async def _provision_in_storage(self, *, org_id: int, access_key: str, secret_key: str) -> None:
        # Each public method here runs its own one-off `asyncio.run()`
        # (see the module docstring), so there is no long-lived event loop
        # to cache a gateway/aiohttp session across calls. A session created
        # in one `asyncio.run()` cannot be reused once that loop closes.
        # Explicitly closing it here (StorageAdminGateway.close()) is the
        # correct fix for this call shape.
        gateway = StorageAdminGateway(
            host=self._host,
            access_key=self._root_access_key,
            secret_key=self._root_secret_key,
        )
        try:
            await gateway.add_user(access_key, secret_key)
            policy = build_org_user_policy(
                bucket=self._bucket, org_prefix=org_storage_prefix(org_id)
            )
            await gateway.create_named_policy(_org_policy_name(org_id), policy)
            await gateway.attach_named_policy(_org_policy_name(org_id), access_key)
        finally:
            await gateway.close()

    async def _deprovision_in_storage(self, *, org_id: int, access_key: str) -> None:
        gateway = StorageAdminGateway(
            host=self._host,
            access_key=self._root_access_key,
            secret_key=self._root_secret_key,
        )
        try:
            await gateway.remove_user(access_key)
            try:
                await gateway.remove_named_policy(_org_policy_name(org_id))
            except Exception as error:
                # The named policy may not exist if a previous provisioning
                # attempt failed partway through -- this is best-effort
                # cleanup, not a reason to fail the whole deprovision.
                logger.error(
                    "Failed to remove storage policy for org_id={}: {}",
                    org_id,
                    error,
                )
        finally:
            await gateway.close()


org_storage_provisioning_service = OrgStorageProvisioningService()
