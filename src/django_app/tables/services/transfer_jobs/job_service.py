"""Starting transfer jobs: the checks a job passes before it is queued."""

import uuid
from dataclasses import asdict

from django.db import transaction
from django.db.models import Count, Q
from rbac.models import Organization
from tables.exceptions import ExportEntitiesNotFoundError, TooManyTransferJobsError
from tables.import_export.enums import EntityType
from tables.import_export.schemas import ImportSettings
from tables.models import TransferJob
from tables.models.user import User
from tables.services.import_export_service import check_job_archive
from tables.services.transfer_jobs.archive_store import TransferArchiveStore
from tables.services.transfer_jobs.queue import enqueue_transfer_job
from tables.services.transfer_jobs.runner import IMPORT_ARCHIVE_NAME, MAIN_ENTITY_MODELS
from utils.logger import logger

# Unfinished (queued or running) jobs one user may have in one organization, and
# that one organization may have in all. Each job holds a container's worker and a
# temporary archive on disk until it finishes.
MAX_UNFINISHED_JOBS_PER_USER = 3
MAX_UNFINISHED_JOBS_PER_ORG = 10

_UNFINISHED_STATUSES = (TransferJob.Status.QUEUED, TransferJob.Status.RUNNING)


class TransferJobService:
    """Create transfer jobs within the per-user and per-organization limits."""

    def start_export(
        self,
        *,
        user: User,
        org_id: int,
        entity_type: EntityType,
        ids: list[int],
        include_knowledge: bool | None = None,
    ) -> TransferJob:
        """Queue an export of the items `ids` of `org_id`, owned by `user`.

        The job is handed to the background consumer once the transaction commits.
        The caller has already checked `user`'s EXPORT right; the runner checks it again.

        Args:
            ids: Distinct ids of `entity_type` items; every one must be in `org_id`.
            include_knowledge: Whether a flow export carries the knowledge collections
                its nodes use. None leaves it out of the job's request, for main
                entities it does not apply to.

        Raises:
            ExportEntitiesNotFoundError: An id is no item of `org_id`.
            TooManyTransferJobsError: `user` or `org_id` is at its unfinished-job limit.
        """
        model = MAIN_ENTITY_MODELS[entity_type][0]
        found = model.objects.filter(pk__in=ids, org_id=org_id).count()
        if found != len(ids):
            raise ExportEntitiesNotFoundError()

        request = {"ids": ids}
        if include_knowledge is not None:
            request["include_knowledge"] = include_knowledge

        with transaction.atomic():
            self._lock_job_creation(org_id)
            self._assert_below_limits(user=user, org_id=org_id)
            job = TransferJob.objects.create(
                org_id=org_id,
                created_by=user,
                kind=TransferJob.Kind.EXPORT,
                main_entity=entity_type.value,
                request=request,
            )
            transaction.on_commit(lambda: enqueue_transfer_job(job))
        return job

    def start_import(
        self,
        *,
        user: User,
        org_id: int,
        entity_type: EntityType,
        settings: ImportSettings | None,
        archive_path: str,
        store: TransferArchiveStore | None = None,
    ) -> TransferJob:
        """Store the archive at `archive_path` and queue its import into `org_id`, owned by `user`.

        The archive is checked first (`check_job_archive`), so a refused one is never
        stored. It is then stored under a job id made here, and the job row is created
        once the limits are checked again under the organization's lock. If anything
        fails after the archive is stored, the stored archive is deleted and no job
        is left. The caller has already checked `user`'s CREATE right (and UPDATE for
        `replace_existing`), and keeps owning the file at `archive_path`.

        Args:
            settings: The import settings of a flow import; None for an import that
                takes none, which runs with the defaults.

        Raises:
            InvalidArchiveError, ValidationError,
            FlowWithTriggerNodesRequiresUsePermissionError: See `check_job_archive`.
            TooManyTransferJobsError: `user` or `org_id` is at its unfinished-job limit.
        """
        check_job_archive(archive_path, main_entity=entity_type, user=user, org_id=org_id)

        store = store if store is not None else TransferArchiveStore()
        job_id = uuid.uuid4()
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
                    request={"settings": asdict(settings) if settings is not None else {}},
                    archive_key=archive_key,
                )
                transaction.on_commit(lambda: enqueue_transfer_job(job))
        except BaseException:
            _discard_archive(store, job_id)
            raise
        return job

    def check_limits(self, *, user: User, org_id: int) -> None:
        """Refuse early when `user` or `org_id` is at its unfinished-job limit.

        Takes no lock, so it only spares a doomed upload: starting the job checks
        the limits again, atomically.

        Raises:
            TooManyTransferJobsError: `user` or `org_id` is at its unfinished-job limit.
        """
        self._assert_below_limits(user=user, org_id=org_id)

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
    def _assert_below_limits(*, user: User, org_id: int) -> None:
        counts = TransferJob.objects.filter(
            org_id=org_id, status__in=_UNFINISHED_STATUSES
        ).aggregate(
            in_org=Count("pk"),
            by_user=Count("pk", filter=Q(created_by=user)),
        )
        if (
            counts["by_user"] >= MAX_UNFINISHED_JOBS_PER_USER
            or counts["in_org"] >= MAX_UNFINISHED_JOBS_PER_ORG
        ):
            raise TooManyTransferJobsError()


def _discard_archive(store: TransferArchiveStore, job_id: uuid.UUID) -> None:
    # Runs while another error is on its way out; that one is what the caller must see.
    try:
        store.delete_job(job_id)
    except Exception:
        logger.exception("Could not delete the archive of refused import job {}", job_id)
