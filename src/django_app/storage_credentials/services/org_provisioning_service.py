"""Provisions and deprovisions the long-lived, org-level MinIO IAM user each
organization owns.

Sync/async boundary: `OrganizationManagementService.create_organization()`/
`deactivate_organization()` are plain sync Django service methods running
inside `@transaction.atomic`. `miniopy_async` (the only MinIO Admin SDK
available) is async-only. Per the project's async-I/O convention, the two
worlds are never interleaved inside one call: each public method here reads
nothing from the ORM itself, runs the entire MinIO conversation through one
`asyncio.run()`, and only then performs its own sync ORM write
(`OrgCredentialStore`/`Secret.objects...`) once the event loop has exited.
"""

import asyncio
import secrets as secrets_module

from django.conf import settings
from loguru import logger

from tables.models.rbac_models import Organization

from storage_credentials.clients.minio_admin_client import MinioAdminGateway
from storage_credentials.constants import ORG_USER_POLICY_NAME_PREFIX
from storage_credentials.exceptions import OrgStorageProvisioningError
from storage_credentials.policies import build_org_user_policy
from storage_credentials.services.org_credential_store import org_credential_store


def _org_prefix(org_id: int) -> str:
    return f"org_{org_id}"


def _org_access_key(org_id: int) -> str:
    return f"org{org_id}storageuser"


def _org_policy_name(org_id: int) -> str:
    return f"{ORG_USER_POLICY_NAME_PREFIX}_{org_id}"


class OrgStorageProvisioningService:
    def __init__(self):
        self._host = settings.STORAGE_ENDPOINT
        self._root_access_key = settings.STORAGE_ACCESS_KEY
        self._root_secret_key = settings.STORAGE_SECRET_KEY
        self._bucket = settings.STORAGE_BUCKET_NAME

    def provision_for_organization(self, org: Organization) -> None:
        """Create a new org-level MinIO IAM user scoped to `org_<id>/*`, and
        persist its credentials as `Secret(system=True)`. Called from inside
        `create_organization()`'s transaction; any failure here propagates
        so the whole organization-creation transaction rolls back -- an
        organization without provisioned storage is not a valid state.
        """
        access_key = _org_access_key(org.id)
        secret_key = secrets_module.token_urlsafe(32)
        try:
            asyncio.run(
                self._provision_in_minio(
                    org_id=org.id, access_key=access_key, secret_key=secret_key
                )
            )
        except Exception as error:
            raise OrgStorageProvisioningError(
                f"Failed to provision MinIO storage user for org_id={org.id}: {error}"
            ) from error

        org_credential_store.save(org=org, access_key=access_key, secret_key=secret_key)
        logger.info("Provisioned org-level MinIO storage user for org_id={}", org.id)

    def deprovision_for_organization(self, org: Organization) -> None:
        """Remove the org-level MinIO user (cascades to revoke every active
        service account it minted) and mark the stored `Secret` as revoked.
        Objects already written under `org_<id>/*` are left untouched
        (retention policy is out of scope -- see plan section 1)."""
        access_key = _org_access_key(org.id)
        try:
            asyncio.run(self._deprovision_in_minio(access_key=access_key))
        except Exception as error:
            raise OrgStorageProvisioningError(
                f"Failed to deprovision MinIO storage user for org_id={org.id}: {error}"
            ) from error

        org_credential_store.mark_revoked(org_id=org.id)
        logger.info("Deprovisioned org-level MinIO storage user for org_id={}", org.id)

    async def _provision_in_minio(
        self, *, org_id: int, access_key: str, secret_key: str
    ) -> None:
        gateway = MinioAdminGateway(
            host=self._host,
            access_key=self._root_access_key,
            secret_key=self._root_secret_key,
        )
        await gateway.add_user(access_key, secret_key)
        policy = build_org_user_policy(
            bucket=self._bucket, org_prefix=_org_prefix(org_id)
        )
        await gateway.create_named_policy(_org_policy_name(org_id), policy)
        await gateway.attach_named_policy(_org_policy_name(org_id), access_key)

    async def _deprovision_in_minio(self, *, access_key: str) -> None:
        gateway = MinioAdminGateway(
            host=self._host,
            access_key=self._root_access_key,
            secret_key=self._root_secret_key,
        )
        await gateway.remove_user(access_key)


org_storage_provisioning_service = OrgStorageProvisioningService()
