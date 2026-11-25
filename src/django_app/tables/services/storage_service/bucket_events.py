"""Keep the file index in step with the bucket, from the store's own change notifications.

Run code (python code nodes, realtime agent tools) writes straight to the store with a
temporary account, past the upload quota check, and its reports to django are only hints.
The store tells django about every object created or removed in the bucket (a webhook
notification target, see the `storage` service in docker-compose). Each record names a key,
and nothing else in it is believed: the key's object is read again from the store and its
row made to match (`StorageReconciler.reconcile_file`). Applying a record twice, late, or a
forged one changes nothing a re-read would not.

Records written by django's own storage account are skipped: the app indexes its own writes
in the same request, and the event can reach django between the app's store write and its
own row update (an upload, a rename, a copy), where a reconcile would race it: a rename's
delete event would drop the row the app is about to move, cascading its flow attachments.

An organization over its quota after its records are applied gets every temporary storage
account revoked, so a run that fills the store is cut off now, not when it ends.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from urllib.parse import unquote_plus

from django.conf import settings
from django.db import transaction
from rbac.models import Organization
from tables.services.storage_service import get_storage_backend
from tables.services.storage_service.path_utils import is_canonical_path, is_trash_path
from tables.services.storage_service.quota import is_over_quota
from tables.services.storage_service.reconciler import StorageReconciler
from tables.validators.file_upload_validator import FileValidator
from utils.logger import logger

_ORG_KEY = re.compile(r"^org_(\d+)/(.+)$")
_CREATED_EVENT_PREFIX = "s3:ObjectCreated:"


@dataclass(frozen=True)
class BucketObjectChange:
    """One object the store reports created or removed, under an organization's prefix."""

    org_id: int
    key: str
    path: str
    created: bool


def changes_from_notification(payload: dict) -> list[BucketObjectChange]:
    """The records of a store notification that concern an organization's live files.

    Skipped: other buckets, keys outside `org_<id>/`, folder markers (a key ending in "/",
    which the app indexes through its folder rows), the recycle bin (managed by the app), and
    records written by django's own storage account.
    """
    changes = []
    for record in payload.get("Records") or []:
        s3 = record.get("s3") or {}
        if (s3.get("bucket") or {}).get("name") != settings.STORAGE_BUCKET_NAME:
            continue
        principal = (record.get("userIdentity") or {}).get("principalId")
        if principal == settings.STORAGE_ACCESS_KEY:
            continue
        key = unquote_plus((s3.get("object") or {}).get("key") or "")
        match = _ORG_KEY.match(key)
        if match is None:
            continue
        path = match.group(2)
        if path.endswith("/") or is_trash_path(path):
            continue
        changes.append(
            BucketObjectChange(
                org_id=int(match.group(1)),
                key=key,
                path=path,
                created=str(record.get("eventName") or "").startswith(_CREATED_EVENT_PREFIX),
            )
        )
    return changes


def delete_executable_object(change: BucketObjectChange) -> None:
    """Delete an executable object run code wrote: it is never indexed, so never counted,
    shown or downloadable, and kept it would be storage outside the quota.

    NOTE: destructive. Whether code-written executables are deleted, or kept and counted some
    other way, is a product decision; this is the one place that makes it.
    """
    logger.warning(
        "Deleting executable object {} written to storage in org {}", change.path, change.org_id
    )
    get_storage_backend(organization_prefix="").delete_keys([change.key])


def delete_non_canonical_object(change: BucketObjectChange) -> None:
    """Delete an object run code wrote under a path the index cannot name.

    A re-read would look up the normalized path, another key, so the object would get no row
    and its bytes would stay outside the quota while the run goes on. The exact key notified
    is deleted, never the normalized one.
    """
    logger.warning(
        "Deleting object {!r} written to storage in org {}: not a canonical path",
        change.path,
        change.org_id,
    )
    get_storage_backend(organization_prefix="").delete_keys([change.key])


class BucketEventService:
    """Apply the store's change notifications to the file index."""

    def __init__(self, reconciler: StorageReconciler | None = None):
        self._reconciler = reconciler or StorageReconciler(
            get_storage_backend(organization_prefix="")
        )
        self._file_validator = FileValidator()

    def apply(self, changes: Iterable[BucketObjectChange]) -> None:
        """Re-read each changed object into the index, then cut off organizations over quota.

        Raises:
            Exception: The store or the database could not be reached. Nothing is lost: the
                store keeps the notification and sends it again, and applying it twice is safe.
        """
        org_ids = []
        for change in changes:
            if not self._apply_one(change):
                continue
            if change.org_id not in org_ids:
                org_ids.append(change.org_id)
        for org_id in org_ids:
            if is_over_quota(org_id):
                self._revoke_run_storage(org_id)

    def _apply_one(self, change: BucketObjectChange) -> bool:
        """Apply one change; False when its organization no longer exists."""
        if not is_canonical_path(change.path):
            # Never re-read: the lookup would name the normalized path, another object.
            if change.created:
                delete_non_canonical_object(change)
            return True
        if change.created and self._file_validator.is_executable_filename(change.path):
            delete_executable_object(change)
            return True
        with transaction.atomic():
            # The org row lock uploads, restores and quota checks take: two notifications of
            # one key applied at once could otherwise each read the store before the other
            # wrote its row, and leave the row of the older state.
            if Organization.objects.select_for_update().filter(pk=change.org_id).first() is None:
                logger.info(
                    "Ignoring storage notification for {}: org {} does not exist",
                    change.path,
                    change.org_id,
                )
                return False
            try:
                self._reconciler.reconcile_file(change.org_id, change.path)
            except ValueError as error:
                # A key the store holds but the index cannot (an invalid name).
                logger.warning(
                    "Cannot index {} of org {} from a storage notification: {}",
                    change.path,
                    change.org_id,
                    error,
                )
        return True

    @staticmethod
    def _revoke_run_storage(org_id: int) -> None:
        from storage_credentials.services.session_credential_service import (
            session_credential_service,
        )

        logger.warning(
            "Org {} is over its storage quota: revoking its runs' storage accounts", org_id
        )
        session_credential_service.revoke_for_organization(org_id)
