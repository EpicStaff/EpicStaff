"""Idempotent pass over every active organization, ensuring each has a
provisioned org-level MinIO user + `Secret(system=True)` row.

Provisioning (`OrgStorageProvisioningService`) is itself idempotent: `user_
add` upserts (creates the MinIO user or resets its secret key if it already
exists), `policy_add`/`policy_set` are both safe to repeat, and
`OrgCredentialStore.save()` always deletes any prior row for the (org, name)
pair before inserting -- so calling it again for an org that turns out to
already have a live MinIO user (but a missing/revoked Secret, e.g. after a
partial failure) still converges to a correct, decryptable Secret. This
command only decides *whether* to call it, not how to merge partial state.
"""

from django.core.management.base import BaseCommand
from loguru import logger

from tables.models.rbac_models import Organization

from storage_credentials.exceptions import OrgStorageProvisioningError
from storage_credentials.services.org_credential_store import org_credential_store
from storage_credentials.services.org_provisioning_service import (
    org_storage_provisioning_service,
)


class Command(BaseCommand):
    help = (
        "Ensure every active organization has a provisioned org-level MinIO "
        "storage user and a matching Secret(system=True) row."
    )

    def handle(self, *args, **options):
        organizations = Organization.objects.filter(is_active=True)
        provisioned = 0
        skipped = 0
        failed = 0

        for org in organizations:
            if org_credential_store.exists(org_id=org.id):
                skipped += 1
                continue
            try:
                org_storage_provisioning_service.provision_for_organization(org)
                provisioned += 1
                self.stdout.write(f"[org={org.id}] provisioned")
            except OrgStorageProvisioningError as error:
                failed += 1
                logger.error(
                    "backfill_org_storage_credentials: org_id={} failed: {}",
                    org.id,
                    error,
                )
                self.stderr.write(f"[org={org.id}] FAILED: {error}")

        self.stdout.write(
            f"Done: provisioned={provisioned} skipped={skipped} failed={failed}"
        )
