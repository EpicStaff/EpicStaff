"""Starting transfer jobs within their limits, and removing them."""

import contextlib
import uuid
from collections import Counter
from collections.abc import Iterator
from dataclasses import asdict
from functools import partial

from django.db import close_old_connections, transaction
from django.db.models import Count, Q, QuerySet
from rbac.models import Organization
from rest_framework.exceptions import NotFound
from tables.exceptions import (
    ExportEntitiesNotFoundError,
    TooManyTransferJobsError,
    TransferJobRunningError,
)
from tables.import_export.enums import EntityType
from tables.import_export.schemas import ImportSettings
from tables.models import TransferJob
from tables.models.user import User
from tables.services.import_export_service import check_job_archive
from tables.services.transfer_jobs.archive_store import TransferArchiveStore
from tables.services.transfer_jobs.export_definitions import ExportJobDefinition
from tables.services.transfer_jobs.queue import enqueue_transfer_job
from tables.services.transfer_jobs.runner import IMPORT_ARCHIVE_NAME
from utils.logger import logger

# Unfinished (queued or running) jobs one user may have in one organization, and
# that one organization may have in all. Each job holds a container's worker and a
# temporary archive on disk until it finishes. An import upload still receiving its
# body counts against the per-user limit too (`ImportUploadsInProgress`).
MAX_UNFINISHED_JOBS_PER_USER = 3
MAX_UNFINISHED_JOBS_PER_ORG = 10

_UNFINISHED_STATUSES = (TransferJob.Status.QUEUED, TransferJob.Status.RUNNING)


class TransferJobService:
    """Create transfer jobs within the per-user and per-organization limits, and remove them."""

    def start_export(
        self,
        *,
        user: User,
        org_id: int,
        definition: ExportJobDefinition,
        validated_data: dict,
    ) -> TransferJob:
        """Queue an export of `definition`'s main entity from `org_id`, owned by `user`.

        The job is handed to the background consumer of the definition's lane once
        the transaction commits. A failed hand-off is only logged: the job stays
        queued until the sweep fails it as `job_not_started`, which the polling
        client then sees. The caller has already checked `user`'s right
        (`definition.permission`); the runner checks it again.

        Args:
            validated_data: The validated body of the `export-jobs` action, with
                `ids` of distinct items; every one must be in
                `definition.scoped_queryset` for `user` and `org_id`.

        Raises:
            ExportEntitiesNotFoundError: An id is no item `user` may export from `org_id`.
            TooManyTransferJobsError: `user` or `org_id` is at its unfinished-job limit.
        """
        request = definition.build_request(validated_data)
        selected = definition.scoped_queryset(user=user, org_id=org_id).filter(
            pk__in=request["ids"]
        )
        if selected.count() != len(request["ids"]):
            raise ExportEntitiesNotFoundError()
        display_name = definition.display_name(selected, request)

        with transaction.atomic():
            self._lock_job_creation(org_id)
            self._assert_below_limits(user=user, org_id=org_id)
            job = TransferJob.objects.create(
                org_id=org_id,
                created_by=user,
                kind=TransferJob.Kind.EXPORT,
                main_entity=definition.main_entity,
                display_name=_fit_display_name(display_name),
                request=request,
            )
            transaction.on_commit(lambda: enqueue_transfer_job(job), robust=True)
        return job

    def start_import(
        self,
        *,
        user: User,
        org_id: int,
        entity_type: EntityType,
        settings: ImportSettings | None,
        archive_path: str,
        file_name: str = "",
        store: TransferArchiveStore | None = None,
    ) -> TransferJob:
        """Store the archive at `archive_path` and queue its import into `org_id`, owned by `user`.

        The archive is checked first (`check_job_archive`), so a refused one is never
        stored. It is then stored under a job id made here, and the job row is created
        once the limits are checked again under the organization's lock. If anything
        fails after the archive is stored and before the job row is committed, the
        stored archive is deleted and no job is left; a failed hand-off to the
        consumer after the commit is handled as in `start_export`. The caller has
        already checked `user`'s CREATE right (and UPDATE for `replace_existing`),
        and keeps owning the file at `archive_path`.

        Args:
            settings: The import settings of a flow import; None for an import that
                takes none, which runs with the defaults.
            file_name: Name of the uploaded file, shown in the job list.

        Raises:
            InvalidArchiveError, ValidationError,
            FlowWithTriggerNodesRequiresUsePermissionError: See `check_job_archive`.
            TooManyTransferJobsError: `user` or `org_id` is at its unfinished-job limit.
        """
        check_job_archive(archive_path, main_entity=entity_type, user=user, org_id=org_id)

        store = store if store is not None else TransferArchiveStore()
        job_id = uuid.uuid4()
        # The upload can take minutes; a connection kept checked out across it holds
        # a pool slot for nothing. Inside a caller's transaction it cannot be given
        # back without breaking that transaction, so it is kept then.
        if not transaction.get_connection().in_atomic_block:
            close_old_connections()
        committed = False
        try:
            with open(archive_path, "rb") as archive:
                archive_key = store.upload_file(job_id, IMPORT_ARCHIVE_NAME, archive)
            with transaction.atomic():
                self._lock_job_creation(org_id)
                self._assert_below_limits(user=user, org_id=org_id)
                job = TransferJob.objects.create(
                    id=job_id,
                    org_id=org_id,
                    created_by=user,
                    kind=TransferJob.Kind.IMPORT,
                    main_entity=entity_type.value,
                    display_name=_fit_display_name(file_name),
                    request={"settings": asdict(settings) if settings is not None else {}},
                    archive_key=archive_key,
                )
                transaction.on_commit(lambda: enqueue_transfer_job(job), robust=True)
            committed = True
        except BaseException:
            # Once the row is committed the archive is the job's: the runner or the
            # sweep deletes it.
            if not committed:
                _discard_archive(store, job_id)
            raise
        return job

    def check_limits(self, *, user: User, org_id: int, uploads_in_progress: int) -> None:
        """Refuse an import upload when `user` or `org_id` is at its unfinished-job limit.

        Takes no lock: starting the job checks the job rows again, atomically.

        Args:
            uploads_in_progress: `user`'s other import uploads in `org_id` still
                receiving their body (`ImportUploadsInProgress`); each counts as
                an unfinished job of `user`.

        Raises:
            TooManyTransferJobsError: `user` or `org_id` is at its unfinished-job limit.
        """
        self._assert_below_limits(user=user, org_id=org_id, uploads_by_user=uploads_in_progress)

    @staticmethod
    def owned_jobs(user: User | None, org_id: int) -> QuerySet[TransferJob]:
        """Return the jobs `user` created in `org_id`, the only ones `user` may see or remove.

        A caller who is no user (a system API key, a plugin service account) owns
        no job. That is checked here rather than left to the filter, because jobs
        whose creator was deleted have no creator either.
        """
        if user is None:
            return TransferJob.objects.none()
        return TransferJob.objects.filter(org_id=org_id, created_by=user)

    def remove_job(self, *, job_id: uuid.UUID, user: User | None, org_id: int) -> None:
        """Delete one of `user`'s jobs in `org_id` that is not running, and then its archive.

        The row stays locked from the status check until the commit, so the runner's
        claim (`TransferJobRunner.run`) waits and then finds it gone: a queued job
        removed here never runs. The stored archive is deleted after the commit;
        one that cannot be is left to the sweep.

        Raises:
            NotFound: No such job of `user` in `org_id`, a job deleted meanwhile included.
            TransferJobRunningError: The job is running; it can be removed once it finishes.
        """
        with transaction.atomic():
            job = (
                self.owned_jobs(user, org_id)
                .filter(pk=job_id)
                .select_for_update()
                .values("pk", "status", "archive_key")
                .first()
            )
            if job is None:
                raise NotFound()
            if job["status"] == TransferJob.Status.RUNNING:
                raise TransferJobRunningError()
            TransferJob.objects.filter(pk=job_id).delete()
            _delete_archives_on_commit([job])

    def remove_jobs(self, *, user: User | None, org_id: int) -> int:
        """Delete every job of `user` in `org_id` that is not running, then their archives.

        Running jobs are kept. As in `remove_job`, the rows stay locked until the
        commit, so a queued job removed here never runs.

        Returns:
            How many jobs were deleted; 0 when there was none to delete.
        """
        with transaction.atomic():
            # Locked in id order, so two concurrent removals cannot deadlock each other.
            # The sweep's multi-row UPDATE of stale queued jobs locks in no fixed order
            # and can still deadlock with this; Postgres then aborts one side, and the
            # caller (or the next sweep) simply runs again.
            jobs = list(
                self.owned_jobs(user, org_id)
                .exclude(status=TransferJob.Status.RUNNING)
                .select_for_update()
                .order_by("pk")
                .values("pk", "archive_key")
            )
            if not jobs:
                return 0
            _, deleted_by_model = TransferJob.objects.filter(
                pk__in=[job["pk"] for job in jobs]
            ).delete()
            _delete_archives_on_commit(jobs)
        return deleted_by_model.get(TransferJob._meta.label, 0)

    @staticmethod
    def _lock_job_creation(org_id: int) -> None:
        # Serializes job creation per organization, so two requests cannot both see
        # room under a limit. With no unfinished jobs there is no job row to lock,
        # so the organization row is locked instead. NO KEY UPDATE does not block
        # rows being inserted with a foreign key to the organization.
        list(
            Organization.objects.select_for_update(no_key=True)
            .filter(pk=org_id)
            .values_list("pk", flat=True)
        )

    @staticmethod
    def _assert_below_limits(*, user: User, org_id: int, uploads_by_user: int = 0) -> None:
        counts = TransferJob.objects.filter(
            org_id=org_id, status__in=_UNFINISHED_STATUSES
        ).aggregate(
            in_org=Count("pk"),
            by_user=Count("pk", filter=Q(created_by=user)),
        )
        if (
            counts["by_user"] + uploads_by_user >= MAX_UNFINISHED_JOBS_PER_USER
            or counts["in_org"] >= MAX_UNFINISHED_JOBS_PER_ORG
        ):
            raise TooManyTransferJobsError()


class ImportUploadsInProgress:
    """Import uploads of this worker still receiving their body, per organization and user.

    Such an upload has no job row yet, so the unfinished-job limit cannot see it in
    the database; it is counted here for as long as it is held. Per worker, like the
    storage upload slots (`UploadAdmission`): used only from the worker's event loop,
    so the counter needs no lock.
    """

    def __init__(self):
        self._uploads: Counter[tuple[int, int]] = Counter()

    @contextlib.contextmanager
    def hold(self, *, org_id: int, user_id: int) -> Iterator[int]:
        """Count one upload of `user_id` in `org_id` for the block; released on every exit.

        Yields how many other uploads of that user in that organization were held
        when this one started.
        """
        key = (org_id, user_id)
        others = self._uploads[key]
        self._uploads[key] += 1
        try:
            yield others
        finally:
            self._uploads[key] -= 1
            if not self._uploads[key]:
                del self._uploads[key]


import_uploads_in_progress = ImportUploadsInProgress()


def _fit_display_name(name: str) -> str:
    max_length = TransferJob._meta.get_field("display_name").max_length
    return name if len(name) <= max_length else f"{name[: max_length - 1]}…"


def _delete_archives_on_commit(jobs: list[dict]) -> None:
    # A job without an archive key has nothing stored: it was never started, its
    # export failed before the upload, or its archive was removed for newer ones.
    job_ids = [job["pk"] for job in jobs if job["archive_key"]]
    if job_ids:
        transaction.on_commit(partial(_delete_stored_archives, job_ids), robust=True)


def _delete_stored_archives(job_ids: list[uuid.UUID]) -> None:
    # The job rows are gone already; an archive left behind is the sweep's to delete.
    store = TransferArchiveStore()
    for job_id in job_ids:
        try:
            store.delete_job(job_id)
        except Exception:
            logger.exception("Could not delete the archive of removed transfer job {}", job_id)


def _discard_archive(store: TransferArchiveStore, job_id: uuid.UUID) -> None:
    # Runs while another error is on its way out; that one is what the caller must see.
    try:
        store.delete_job(job_id)
    except Exception:
        logger.exception("Could not delete the archive of refused import job {}", job_id)
