"""Running export and import jobs in the background, and sweeping old ones away."""

import os
from datetime import datetime, timedelta
from functools import partial
from uuid import UUID

from django.utils import timezone
from rbac.access.asserts import assert_org_permission
from rbac.models.enums import Permission
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError
from tables.clients.errors import ClientError
from tables.import_export.archive import temporary_archive
from tables.import_export.enums import EntityType
from tables.import_export.export_format_strategies import ArchiveExportFormatStrategy
from tables.import_export.permissions import ENTITY_RESOURCE_MAP, ExportAccessPolicy
from tables.import_export.registry import entity_registry
from tables.import_export.schemas import ImportSettings
from tables.import_export.services.export_service import ExportService
from tables.models import Graph, TransferJob
from tables.models.knowledge_models import SourceCollection
from tables.services.import_export_service import ViewSetImportExportService
from tables.services.transfer_jobs.archive_store import TransferArchiveStore
from tables.utils.helpers import generate_file_name
from utils.exception_handler import flatten_error_detail
from utils.logger import logger

# A job still running after this long was cut off (its container stopped); the sweep fails it.
TRANSFER_JOB_STALE_AFTER = timedelta(hours=2)

EXPORT_ARCHIVE_NAME = "export.zip"
IMPORT_ARCHIVE_NAME = "import.zip"

# The main entities a job carries: their model, and the prefix of their archive's name.
_MAIN_MODELS = {
    EntityType.GRAPH: (Graph, "flow"),
    EntityType.SOURCE_COLLECTION: (SourceCollection, "knowledge"),
}


class TransferJobError(Exception):
    """A failure the job's creator may be told about, as `{code, message}`."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def public_error(error: Exception) -> dict:
    """Describe `error` for the job's creator: a code and a message, never a traceback."""
    if isinstance(error, TransferJobError):
        return {"code": error.code, "message": error.message}
    if isinstance(error, ValidationError):
        detail = error.detail
        if isinstance(detail, dict) and "code" in detail:
            return {"code": str(detail["code"]), "message": str(detail.get("detail", ""))}
        return {"code": "invalid_file", "message": flatten_error_detail(detail)}
    # PermissionDenied, and the 403 a creator who left the organization gets.
    if isinstance(error, PermissionDenied) or getattr(error, "status_code", None) == 403:
        return {"code": "permission_denied", "message": str(error.detail)}
    if isinstance(error, ClientError):
        return {
            "code": "knowledge_service_unavailable",
            "message": "The knowledge service could not take the graph index.",
        }
    if isinstance(error, APIException):
        return {"code": "invalid_file", "message": str(error.detail)}
    return {"code": "internal_error", "message": "The job failed unexpectedly."}


class TransferJobRunner:
    """Run one job with its creator's permissions in its organization."""

    def __init__(self, store: TransferArchiveStore | None = None):
        self._store = store if store is not None else TransferArchiveStore()

    def run(self, job_id: UUID) -> None:
        """Run the job if it is still queued; anything else is left alone.

        The job ends `completed` or `failed`; temporary files are always removed,
        and an import's uploaded archive is deleted once the import is done.
        """
        # Claiming by status lets a re-delivered entry find the job already taken.
        started_at = timezone.now()
        # update() skips auto_now, so updated_at is set by hand here and in the sweep.
        claimed = TransferJob.objects.filter(pk=job_id, status=TransferJob.Status.QUEUED).update(
            status=TransferJob.Status.RUNNING, started_at=started_at, updated_at=started_at
        )
        if not claimed:
            logger.info("Transfer job {} is not queued any more; skipped", job_id)
            return

        job = TransferJob.objects.select_related("created_by").get(pk=job_id)
        try:
            if job.created_by is None:
                raise TransferJobError("creator_missing", "The user who started the job is gone.")
            if job.kind == TransferJob.Kind.EXPORT:
                self._export(job)
            else:
                self._import(job)
            job.status = TransferJob.Status.COMPLETED
        except Exception as error:
            logger.exception("Transfer job {} failed", job_id)
            job.status = TransferJob.Status.FAILED
            job.error = public_error(error)
        finally:
            job.finished_at = timezone.now()
            job.save(
                update_fields=[
                    "status",
                    "archive_key",
                    "file_name",
                    "result",
                    "error",
                    "finished_at",
                    "updated_at",
                ]
            )
            if job.kind == TransferJob.Kind.IMPORT:
                self._delete_archives(job)

    def _export(self, job: TransferJob) -> None:
        entity_type = EntityType(job.main_entity)
        user, org_id = job.created_by, job.org_id
        # Checked again here: the creator's rights may have changed since the job was queued.
        assert_org_permission(user, org_id, ENTITY_RESOURCE_MAP[entity_type], Permission.EXPORT)
        model, prefix = _MAIN_MODELS[entity_type]
        entity_ids = list(job.request.get("ids", []))
        instances = list(model.objects.filter(pk__in=entity_ids, org_id=org_id))
        if not entity_ids or len(instances) != len(set(entity_ids)):
            raise TransferJobError("not_found", "Some of the requested items do not exist.")

        result = ExportService(entity_registry).export_entities(
            entity_type,
            entity_ids,
            org_id=org_id,
            policy=ExportAccessPolicy.for_user(user, org_id),
            include_knowledge=job.request.get("include_knowledge", True),
        )
        path = ArchiveExportFormatStrategy().render_to_file(result)
        try:
            with open(path, "rb") as archive:
                job.archive_key = self._store.upload_file(job.id, EXPORT_ARCHIVE_NAME, archive)
        finally:
            os.unlink(path)

        strategy = entity_registry.get_strategy(entity_type)
        base_name = (
            str(strategy.get_preview_data(instances[0])["name"])
            if len(instances) == 1
            else f"bulk_{len(instances)}"
        )
        job.file_name = generate_file_name(base_name, prefix=prefix).replace(".json", ".zip")
        job.result = {
            "excluded": [
                {
                    "entity_type": str(item.entity_type),
                    "entity_id": item.entity_id,
                    "name": item.name,
                }
                for item in result.excluded
            ]
        }

    def _import(self, job: TransferJob) -> None:
        entity_type = EntityType(job.main_entity)
        user, org_id = job.created_by, job.org_id
        assert_org_permission(user, org_id, ENTITY_RESOURCE_MAP[entity_type], Permission.CREATE)
        settings = ImportSettings(**job.request.get("settings", {}))
        if settings.replace_existing:
            assert_org_permission(user, org_id, ENTITY_RESOURCE_MAP[entity_type], Permission.UPDATE)

        _model, prefix = _MAIN_MODELS[entity_type]
        with temporary_archive(partial(self._store.download_to, job.archive_key)) as path:
            job.result = ViewSetImportExportService(
                entity_type=entity_type, export_prefix=prefix, filename_attr="name"
            ).import_archive(
                path, org_id=org_id, user=user, settings=settings, main_entity=entity_type
            )

    def _delete_archives(self, job: TransferJob) -> None:
        try:
            self._store.delete_job(job.id)
        except Exception:
            logger.exception("Could not delete the archive of transfer job {}", job.id)


def sweep_transfer_jobs(now: datetime, store: TransferArchiveStore | None = None) -> dict:
    """Delete expired jobs with their archives, and fail jobs left running.

    Returns how many jobs were deleted and how many were failed.
    """
    store = store if store is not None else TransferArchiveStore()

    interrupted = TransferJob.objects.filter(
        status=TransferJob.Status.RUNNING, started_at__lt=now - TRANSFER_JOB_STALE_AFTER
    ).update(
        status=TransferJob.Status.FAILED,
        finished_at=now,
        updated_at=now,
        error={"code": "job_interrupted", "message": "The job stopped before it finished."},
    )

    deleted = 0
    for job_id in TransferJob.objects.filter(expires_at__lte=now).values_list("id", flat=True):
        try:
            store.delete_job(job_id)
        except Exception:
            # Kept for the next sweep: deleting the row would orphan the archive.
            logger.exception("Could not delete the archive of expired transfer job {}", job_id)
            continue
        TransferJob.objects.filter(pk=job_id).delete()
        deleted += 1

    return {"deleted": deleted, "interrupted": interrupted}
