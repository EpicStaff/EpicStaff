"""Running export and import jobs in the background, and sweeping old ones away."""

import os
from datetime import datetime, timedelta
from functools import partial
from uuid import UUID

from django.conf import settings
from django.utils import timezone
from rbac.access.asserts import assert_org_permission
from rbac.models.enums import Permission
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError
from tables.clients.errors import ClientError, ClientValidationError
from tables.exceptions import CustomAPIExeption, TransferJobArchiveRemovedError
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

# At most this many archives without a job row are deleted per sweep; the rest wait
# for the next one.
MAX_ORPHANED_ARCHIVES_PER_SWEEP = 100

# A job still running after this long was cut off (its container stopped), and one still
# queued after this long lost its stream entry; the sweep fails both.
TRANSFER_JOB_STALE_AFTER = timedelta(hours=2)

# Export archives one user keeps stored in one organization. Each one sits in the
# shared bucket, outside every organization's quota, until it expires; when an
# export completes, the archives of that user's older completed exports past this
# many are deleted.
MAX_STORED_EXPORTS_PER_USER = 3

EXPORT_ARCHIVE_NAME = "export.zip"
IMPORT_ARCHIVE_NAME = "import.zip"

# Left on a completed export whose archive was deleted to keep the newest
# `MAX_STORED_EXPORTS_PER_USER`, so its status says what its download answers.
ARCHIVE_REMOVED_ERROR = {
    "code": TransferJobArchiveRemovedError.default_code,
    "message": TransferJobArchiveRemovedError.default_detail,
}

# The main entities a job carries: their model, and the prefix of their archive's name.
MAIN_ENTITY_MODELS = {
    EntityType.GRAPH: (Graph, "flow"),
    EntityType.SOURCE_COLLECTION: (SourceCollection, "knowledge"),
}


class TransferJobError(Exception):
    """A failure the job's creator may be told about, as `{code, message}`."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def public_error(error: Exception, kind: str) -> dict:
    """Describe `error` for the job's creator: a code and a message, never a traceback.

    Args:
        kind: The job's `TransferJob.Kind`; a refusal from the knowledge service means
            a bad archive on import and an index being rebuilt on export.
    """
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
    if isinstance(error, ClientValidationError):
        if kind == TransferJob.Kind.IMPORT:
            return {
                "code": "invalid_archive",
                "message": "The knowledge service refused the graph index in the archive.",
            }
        return {
            "code": "collection_changed",
            "message": "A graph index is being rebuilt; export again once it is ready.",
        }
    if isinstance(error, ClientError):
        return {
            "code": "knowledge_service_unavailable",
            "message": "The knowledge service could not be reached.",
        }
    # A project error names itself (e.g. `export_cycle_detected`); the creator sees that code.
    if isinstance(error, CustomAPIExeption):
        return {"code": error.default_code, "message": flatten_error_detail(error.detail)}
    if isinstance(error, APIException):
        return {"code": "invalid_file", "message": flatten_error_detail(error.detail)}
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
            job.error = public_error(error, job.kind)
        finally:
            self._finish(job)

    def _finish(self, job: TransferJob) -> None:
        """Record the outcome, unless the sweep failed or deleted the job meanwhile.

        Written only over a row still `running`, so an outcome never overwrites the
        sweep's. A completed export makes room for itself by deleting the creator's
        older archives (past `MAX_STORED_EXPORTS_PER_USER`); an export nobody can reach any
        more has its stored archive deleted; an import's uploaded archive is deleted
        either way.
        """
        finished_at = timezone.now()
        # update() skips auto_now, so updated_at is set by hand.
        recorded = TransferJob.objects.filter(pk=job.id, status=TransferJob.Status.RUNNING).update(
            status=job.status,
            archive_key=job.archive_key,
            file_name=job.file_name,
            result=job.result,
            error=job.error,
            finished_at=finished_at,
            updated_at=finished_at,
        )
        if (
            recorded
            and job.kind == TransferJob.Kind.EXPORT
            and job.status == TransferJob.Status.COMPLETED
        ):
            self._remove_older_export_archives(job)
        if not recorded:
            logger.warning(
                "Transfer job {} was failed or deleted while it ran; its {} outcome is dropped",
                job.id,
                job.status,
            )
        if job.kind == TransferJob.Kind.IMPORT or (not recorded and job.archive_key):
            self._delete_archives(job)

    def _export(self, job: TransferJob) -> None:
        entity_type = EntityType(job.main_entity)
        user, org_id = job.created_by, job.org_id
        # Checked again here: the creator's rights may have changed since the job was queued.
        assert_org_permission(user, org_id, ENTITY_RESOURCE_MAP[entity_type], Permission.EXPORT)
        model, prefix = MAIN_ENTITY_MODELS[entity_type]
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
            # An archive past the import cap could not be imported again, and would
            # only take room in the shared bucket.
            if os.path.getsize(path) > settings.MAX_KNOWLEDGE_ARCHIVE_SIZE:
                raise TransferJobError(
                    "archive_too_large",
                    "The export is larger than the import size limit, so it could not be "
                    "imported again either. Export fewer items, or export without knowledge.",
                )
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

        _model, prefix = MAIN_ENTITY_MODELS[entity_type]
        with temporary_archive(partial(self._store.download_to, job.archive_key)) as path:
            job.result = ViewSetImportExportService(
                entity_type=entity_type, export_prefix=prefix, filename_attr="name"
            ).import_archive(
                path, org_id=org_id, user=user, settings=settings, main_entity=entity_type
            )

    def _remove_older_export_archives(self, job: TransferJob) -> None:
        """Delete the archives of the creator's completed exports in the org past the newest few.

        Each removed job stays `completed`, with no archive and the error
        `archive_removed`, so its status and download say why. An archive that
        could not be deleted keeps its job as it was, to be tried again at the next
        export; the sweep deletes it with its job at the latest.
        """
        older = (
            TransferJob.objects.filter(
                org_id=job.org_id,
                created_by_id=job.created_by_id,
                kind=TransferJob.Kind.EXPORT,
                status=TransferJob.Status.COMPLETED,
            )
            .exclude(archive_key="")
            .order_by("-finished_at", "-created_at")
            .values_list("pk", flat=True)[MAX_STORED_EXPORTS_PER_USER:]
        )
        for job_id in older:
            try:
                self._store.delete_job(job_id)
            except Exception:
                logger.exception("Could not delete the archive of older export job {}", job_id)
                continue
            TransferJob.objects.filter(pk=job_id).update(
                archive_key="",
                error=ARCHIVE_REMOVED_ERROR,
                updated_at=timezone.now(),
            )

    def _delete_archives(self, job: TransferJob) -> None:
        try:
            self._store.delete_job(job.id)
        except Exception:
            logger.exception("Could not delete the archive of transfer job {}", job.id)


def sweep_transfer_jobs(now: datetime, store: TransferArchiveStore | None = None) -> dict:
    """Delete expired jobs with their archives, and fail jobs left running or never started.

    Also deletes stored archives that have no job row (an import refused after its
    upload whose own cleanup failed, or a job deleted without its archive), once
    they are older than `TRANSFER_ARCHIVE_TTL`.

    Returns how many jobs were deleted, failed while running, and failed before
    starting, and how many archives without a job were deleted.
    """
    store = store if store is not None else TransferArchiveStore()
    stale_before = now - TRANSFER_JOB_STALE_AFTER

    interrupted = TransferJob.objects.filter(
        status=TransferJob.Status.RUNNING, started_at__lt=stale_before
    ).update(
        status=TransferJob.Status.FAILED,
        finished_at=now,
        updated_at=now,
        error={"code": "job_interrupted", "message": "The job stopped before it finished."},
    )
    # Its stream entry was lost (or is stuck pending under a container that is gone).
    not_started = TransferJob.objects.filter(
        status=TransferJob.Status.QUEUED, created_at__lt=stale_before
    ).update(
        status=TransferJob.Status.FAILED,
        finished_at=now,
        updated_at=now,
        error={"code": "job_not_started", "message": "The job never started."},
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

    orphans_deleted = _delete_orphaned_archives(now, store)

    return {
        "deleted": deleted,
        "interrupted": interrupted,
        "not_started": not_started,
        "orphans_deleted": orphans_deleted,
    }


def _delete_orphaned_archives(now: datetime, store: TransferArchiveStore) -> int:
    # Only archives older than a job's whole lifetime: a younger one may belong to
    # an import whose row is about to be created after its upload.
    stored_before = now - timedelta(seconds=settings.TRANSFER_ARCHIVE_TTL)
    old_job_ids = [
        job_id for job_id, modified in store.list_jobs().items() if modified <= stored_before
    ]
    with_row = set(TransferJob.objects.filter(pk__in=old_job_ids).values_list("id", flat=True))
    orphans = [job_id for job_id in old_job_ids if job_id not in with_row]
    if len(orphans) > MAX_ORPHANED_ARCHIVES_PER_SWEEP:
        logger.warning(
            "{} transfer archives have no job; deleting {} now, the rest next sweep",
            len(orphans),
            MAX_ORPHANED_ARCHIVES_PER_SWEEP,
        )

    deleted = 0
    for job_id in orphans[:MAX_ORPHANED_ARCHIVES_PER_SWEEP]:
        try:
            store.delete_job(job_id)
        except Exception:
            logger.exception("Could not delete the transfer archive {} that has no job", job_id)
            continue
        logger.info("Deleted the transfer archive {} that has no job", job_id)
        deleted += 1
    return deleted
