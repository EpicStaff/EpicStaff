"""Idempotent pass over every active organization, ensuring each has a
provisioned org-level MinIO user + `Secret(system=True)` row that the storage
server still accepts.

Provisioning (`OrgStorageProvisioningService`) is itself idempotent: `user_
add` upserts (creates the MinIO user or resets its secret key if it already
exists), `policy_add`/`policy_set` are both safe to repeat, and
`OrgCredentialStore.save()` always deletes any prior row for the (org, name)
pair before inserting -- so calling it again for an org that turns out to
already have a live MinIO user (but a missing/revoked Secret, e.g. after a
partial failure) still converges to a correct, decryptable Secret. This
command only decides *whether* to call it, not how to merge partial state.

That same upsert is how a stored secret drifts: provisioning this org id against
the same storage from another database (a reset or restored DB, a test run, a
rolled-back org creation) resets the server's secret, and every request signed
with the stored one then fails with `SignatureDoesNotMatch`. So an existing
Secret is verified against the server and re-provisioned only when the server
rejects it. A server that does not answer never triggers a rotation.

Two live databases provisioning the same org ids against one storage server are
not supported: each start would rotate the other's keys. A key the server still
rejects right after re-provisioning is counted as failed and logged as that likely
cause.
"""

from collections import Counter
from contextlib import contextmanager

from django.core.management.base import BaseCommand
from django.db import connection
from loguru import logger
from rbac.models import Organization

from storage_credentials.exceptions import OrgStorageCredentialCheckError
from storage_credentials.services.org_credential_store import org_credential_store
from storage_credentials.services.org_provisioning_service import (
    org_storage_provisioning_service,
)

_PROVISIONED = "provisioned"
_REPAIRED = "repaired"
_SKIPPED = "skipped"
_UNVERIFIED = "unverified"
_FAILED = "failed"
_OUTCOMES = (_PROVISIONED, _REPAIRED, _SKIPPED, _UNVERIFIED, _FAILED)


@contextmanager
def _org_provisioning_lock(org_id: int):
    """Postgres session-level advisory lock scoped to one org_id, so two
    containers running this backfill at the same time (e.g. a rolling
    restart, or several django_app replicas starting together) cannot both
    provision a different MinIO user for the same org. `pg_try_advisory_lock`
    never blocks: a container that loses the race gets `acquired=False` and
    should skip the org rather than wait, since the other process is
    presumably already provisioning it."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_try_advisory_lock(%s)", [org_id])
        acquired = cursor.fetchone()[0]
    try:
        yield acquired
    finally:
        if acquired:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_unlock(%s)", [org_id])


class Command(BaseCommand):
    help = (
        "Ensure every active organization has a provisioned org-level MinIO "
        "storage user and a matching Secret(system=True) row, re-provisioning "
        "any whose stored credentials the storage server rejects."
    )

    def handle(self, *args, **options):
        counts = Counter()
        storage_answers = True

        for org in Organization.objects.filter(is_active=True):
            try:
                outcome = self._reconcile(org, verify=storage_answers)
            except OrgStorageCredentialCheckError:
                self.stderr.write(f"[org={org.id}] unverified: storage did not answer")
                outcome = _UNVERIFIED
            # This command runs under `set -e` on container start: one org's failure is
            # logged and counted, never allowed to stop the other orgs or the container.
            except Exception:
                logger.exception("backfill_org_storage_credentials: org_id={} failed", org.id)
                self.stderr.write(f"[org={org.id}] FAILED")
                outcome = _FAILED

            if outcome == _UNVERIFIED and storage_answers:
                # The command blocks container start: one unanswered check stands
                # for the rest instead of costing a timeout per organization.
                storage_answers = False
                self.stderr.write(
                    "Storage did not answer; not verifying the remaining organizations."
                )
            counts[outcome] += 1

        summary = " ".join(f"{outcome}={counts[outcome]}" for outcome in _OUTCOMES)
        self.stdout.write(f"Done: {summary}")

    def _reconcile(self, org: Organization, *, verify: bool) -> str:
        if not org_credential_store.exists(org_id=org.id):
            return self._provision_missing(org)
        if not verify:
            return _UNVERIFIED
        return self._repair_if_rejected(org)

    def _provision_missing(self, org: Organization) -> str:
        with _org_provisioning_lock(org.id) as acquired:
            if not acquired:
                return self._skip_locked(org)
            # Another process may have provisioned this org between the first
            # check and acquiring the lock.
            if org_credential_store.exists(org_id=org.id):
                return _SKIPPED
            org_storage_provisioning_service.provision_for_organization(org)
        self.stdout.write(f"[org={org.id}] {_PROVISIONED}")
        return _PROVISIONED

    def _repair_if_rejected(self, org: Organization) -> str:
        """Re-provision the org when the storage server rejects its stored credentials.

        Raises:
            OrgStorageCredentialCheckError: The server did not answer a check.
        """
        if self._rejection_code(org) is None:
            return _SKIPPED

        with _org_provisioning_lock(org.id) as acquired:
            if not acquired:
                return self._skip_locked(org)
            # Another replica may have repaired this org before the lock was ours.
            rejection_code = self._rejection_code(org)
            if rejection_code is None:
                return _SKIPPED

            logger.warning(
                "backfill_org_storage_credentials: storage rejects the stored credentials "
                "of org_id={} ({}); re-provisioning",
                org.id,
                rejection_code,
            )
            org_storage_provisioning_service.provision_for_organization(org)

            rejection_code = self._rejection_code(org)
            if rejection_code is not None:
                logger.error(
                    "backfill_org_storage_credentials: storage still rejects the credentials "
                    "of org_id={} ({}) right after re-provisioning them. Likely another "
                    "database provisioning the same org ids against this storage server, or "
                    "something between Django and the storage altering signed requests.",
                    org.id,
                    rejection_code,
                )
                self.stderr.write(f"[org={org.id}] FAILED: still rejected after re-provisioning")
                return _FAILED

        self.stdout.write(f"[org={org.id}] {_REPAIRED}")
        return _REPAIRED

    def _rejection_code(self, org: Organization) -> str | None:
        return org_storage_provisioning_service.stored_credentials_rejection_code(org.id)

    def _skip_locked(self, org: Organization) -> str:
        self.stdout.write(f"[org={org.id}] skipped (already being provisioned by another process)")
        return _SKIPPED
