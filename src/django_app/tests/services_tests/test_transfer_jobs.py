"""Transfer jobs in the background: running an export or an import with the creator's
rights, the error a creator sees, the files left behind, the sweep, and the consumer."""

import io
import json
import os
import uuid
import zipfile
from datetime import timedelta

import fakeredis
import pytest
from django.utils import timezone

from rbac.models import OrganizationUser, Role
from rbac.models.enums import Permission, ResourceType
from rbac.models.role import RolePermission
from src.shared.redis_streams import (
    TRANSFER_JOB_CONSUMER_GROUP,
    TRANSFER_JOB_STREAM,
    TRANSFER_JOB_SWEEP_REQUESTED_AT_FIELD,
)
from tables.exceptions import ExportCycleError
from tables.import_export.archive import ENVELOPE_MEMBER
from tables.import_export.enums import EntityType
from tables.import_export.export_format_strategies import ArchiveExportFormatStrategy
from tables.import_export.registry import entity_registry
from tables.import_export.services.export_service import ExportService
from tables.models import Graph, TransferJob
from tables.services import organization_deletion
from tables.services.import_export_service import ViewSetImportExportService
from tables.services.organization_deletion import TablesOrganizationDeletion
from tables.services.transfer_jobs.archive_store import TransferArchiveStore
from tables.services.transfer_jobs.consumer import TransferJobConsumer
from tables.services.transfer_jobs.queue import enqueue_transfer_job
from tables.clients.errors import (
    ClientBadGatewayError,
    ClientNotAvailableError,
    ClientTimeoutError,
    ClientValidationError,
)
from tables.services.transfer_jobs import runner as runner_module
from tables.services.transfer_jobs.runner import (
    EXPORT_ARCHIVE_NAME,
    IMPORT_ARCHIVE_NAME,
    TransferJobRunner,
    public_error,
    sweep_transfer_jobs,
)
from tests.helpers import UNRESTRICTED_EXPORT_POLICY
from tests.storage_backend_fake import FakeStorageBackend

pytestmark = pytest.mark.django_db


@pytest.fixture
def backend():
    return FakeStorageBackend()


@pytest.fixture
def store(backend):
    return TransferArchiveStore(backend=backend)


@pytest.fixture
def runner(store):
    return TransferJobRunner(store=store)


@pytest.fixture
def flow(default_org):
    return Graph.objects.create(
        name="Support Flow", metadata={"nodes": [], "edges": []}, org=default_org
    )


def _job(org, user, *, kind, request, archive_key="") -> TransferJob:
    return TransferJob.objects.create(
        org=org,
        created_by=user,
        kind=kind,
        main_entity=TransferJob.MainEntity.FLOW,
        request=request,
        archive_key=archive_key,
    )


def _export_job(flow, user, **request) -> TransferJob:
    return _job(
        flow.org,
        user,
        kind=TransferJob.Kind.EXPORT,
        request={"ids": [flow.id], "include_knowledge": True, **request},
    )


def _import_job(org, user, store, archive: bytes) -> TransferJob:
    job = _job(org, user, kind=TransferJob.Kind.IMPORT, request={"settings": {}})
    job.archive_key = store.upload_file(job.id, IMPORT_ARCHIVE_NAME, io.BytesIO(archive))
    job.save(update_fields=["archive_key"])
    return job


def _flow_archive(flow) -> bytes:
    result = ExportService(entity_registry).export_entities(
        EntityType.GRAPH, [flow.id], policy=UNRESTRICTED_EXPORT_POLICY
    )
    path = ArchiveExportFormatStrategy().render_to_file(result)
    try:
        with open(path, "rb") as archive:
            return archive.read()
    finally:
        os.unlink(path)


@pytest.fixture
def member_without(default_org, django_user_model):
    """A member of the default org whose role lacks one permission on flows."""

    def _make(missing: Permission):
        role = Role.objects.create(name=f"no-{missing.name}", org=default_org, is_built_in=False)
        everything = Permission.READ | Permission.CREATE | Permission.UPDATE | Permission.EXPORT
        RolePermission.objects.create(
            role=role, resource_type=ResourceType.FLOWS, permissions=int(everything & ~missing)
        )
        user = django_user_model.objects.create_user(
            email=f"no-{missing.name.lower()}@example.com", password="StrongPass123!"
        )
        OrganizationUser.objects.create(user=user, org=default_org, role=role)
        return user

    return _make


# --- export ------------------------------------------------------------------------------


def test_export_job_stores_its_archive_and_completes(runner, backend, flow, regular_user):
    job = _export_job(flow, regular_user)

    runner.run(job.id)

    job.refresh_from_db()
    assert job.status == TransferJob.Status.COMPLETED
    assert job.archive_key == f"system/transfers/{job.id}/{EXPORT_ARCHIVE_NAME}"
    assert job.file_name.startswith("flow_support_flow") and job.file_name.endswith(".zip")
    assert job.result == {"excluded": []}
    assert (job.error, job.started_at is not None, job.finished_at is not None) == (
        None,
        True,
        True,
    )
    with zipfile.ZipFile(io.BytesIO(backend.objects[job.archive_key])) as archive:
        envelope = json.loads(archive.read(ENVELOPE_MEMBER))
    assert envelope["main_entity"] == EntityType.GRAPH
    assert [entry["name"] for entry in envelope[EntityType.GRAPH]] == ["Support Flow"]


def test_export_of_an_item_outside_the_org_fails_as_not_found(runner, flow, regular_user):
    job = _export_job(flow, regular_user)
    job.request = {"ids": [flow.id, flow.id + 1000]}
    job.save(update_fields=["request"])

    runner.run(job.id)

    job.refresh_from_db()
    assert (job.status, job.error["code"]) == (TransferJob.Status.FAILED, "not_found")


def test_export_runs_with_the_creators_current_rights(runner, flow, member_without):
    job = _export_job(flow, member_without(Permission.EXPORT))

    runner.run(job.id)

    job.refresh_from_db()
    assert (job.status, job.error["code"]) == (TransferJob.Status.FAILED, "permission_denied")


# --- import ------------------------------------------------------------------------------


def test_import_job_records_the_summary_and_deletes_the_upload(
    runner, backend, store, flow, regular_user, default_org
):
    job = _import_job(default_org, regular_user, store, _flow_archive(flow))

    runner.run(job.id)

    job.refresh_from_db()
    assert job.status == TransferJob.Status.COMPLETED
    assert job.result[EntityType.GRAPH]["created"]["count"] == 1
    assert backend.objects == {}


def test_import_needs_update_rights_to_replace_existing_flows(
    runner, store, flow, member_without, default_org
):
    job = _import_job(default_org, member_without(Permission.UPDATE), store, _flow_archive(flow))
    job.request = {"settings": {"preserve_uuids": True, "replace_existing": True}}
    job.save(update_fields=["request"])

    runner.run(job.id)

    job.refresh_from_db()
    assert (job.status, job.error["code"]) == (TransferJob.Status.FAILED, "permission_denied")


# --- failures ----------------------------------------------------------------------------


def test_a_refused_archive_fails_with_its_code_and_the_upload_is_deleted(
    runner, backend, store, regular_user, default_org
):
    job = _import_job(default_org, regular_user, store, b"definitely not a zip")

    runner.run(job.id)

    job.refresh_from_db()
    assert job.status == TransferJob.Status.FAILED
    assert job.error == {"code": "invalid_archive", "message": "not a zip archive"}
    assert backend.objects == {}


def test_an_unexpected_failure_shows_no_internal_detail(runner, flow, regular_user, monkeypatch):
    def explode(*args, **kwargs):
        raise RuntimeError("database password is hunter2")

    monkeypatch.setattr(ExportService, "export_entities", explode)
    job = _export_job(flow, regular_user)

    runner.run(job.id)

    job.refresh_from_db()
    assert job.error == {"code": "internal_error", "message": "The job failed unexpectedly."}


def test_temporary_files_are_removed_when_a_job_fails(
    runner, store, flow, regular_user, default_org, monkeypatch
):
    written = []
    render = ArchiveExportFormatStrategy.render_to_file

    def recording_render(self, result):
        path = render(self, result)
        written.append(path)
        return path

    def failing_upload(*args, **kwargs):
        raise RuntimeError("storage down")

    downloaded = []

    def failing_import(self, path, **kwargs):
        downloaded.append(path)
        raise RuntimeError("import broke")

    monkeypatch.setattr(ArchiveExportFormatStrategy, "render_to_file", recording_render)
    monkeypatch.setattr(TransferArchiveStore, "upload_file", failing_upload)
    monkeypatch.setattr(ViewSetImportExportService, "import_archive", failing_import)
    export_job = _export_job(flow, regular_user)
    import_job = _job(
        default_org,
        regular_user,
        kind=TransferJob.Kind.IMPORT,
        request={"settings": {}},
        archive_key="system/transfers/x/import.zip",
    )
    store._backend.objects["system/transfers/x/import.zip"] = b"bytes"

    runner.run(export_job.id)
    runner.run(import_job.id)

    assert len(written) == 1 and len(downloaded) == 1
    assert not os.path.exists(written[0])
    assert not os.path.exists(downloaded[0])


def test_a_job_that_is_not_queued_is_left_alone(runner, flow, regular_user):
    job = _export_job(flow, regular_user)
    TransferJob.objects.filter(pk=job.pk).update(status=TransferJob.Status.COMPLETED)

    runner.run(job.id)

    job.refresh_from_db()
    assert (job.status, job.archive_key, job.started_at) == (
        TransferJob.Status.COMPLETED,
        "",
        None,
    )


@pytest.mark.parametrize(
    ("swept", "expected_status"),
    [
        pytest.param("failed", TransferJob.Status.FAILED, id="failed by the sweep"),
        pytest.param("deleted", None, id="deleted by the sweep"),
    ],
)
def test_an_export_the_sweep_took_over_keeps_its_outcome_and_leaves_no_archive(
    runner, backend, flow, regular_user, monkeypatch, swept, expected_status
):
    job = _export_job(flow, regular_user)
    export = ExportService.export_entities

    def export_while_the_sweep_runs(self, *args, **kwargs):
        jobs = TransferJob.objects.filter(pk=job.pk)
        if swept == "failed":
            jobs.update(status=TransferJob.Status.FAILED, error={"code": "job_interrupted"})
        else:
            jobs.delete()
        return export(self, *args, **kwargs)

    monkeypatch.setattr(ExportService, "export_entities", export_while_the_sweep_runs)

    runner.run(job.id)

    row = TransferJob.objects.filter(pk=job.pk).first()
    assert (row.status if row else None) == expected_status
    if row is not None:
        assert row.error == {"code": "job_interrupted"}
    # Nobody can download it any more, so it is not kept.
    assert backend.objects == {}


@pytest.mark.parametrize(
    ("error", "kind", "code"),
    [
        pytest.param(
            ClientValidationError("refused"),
            TransferJob.Kind.IMPORT,
            "invalid_archive",
            id="index refused on import",
        ),
        pytest.param(
            ClientValidationError("not ready"),
            TransferJob.Kind.EXPORT,
            "collection_changed",
            id="index rebuilding on export",
        ),
        pytest.param(
            ClientNotAvailableError("down"),
            TransferJob.Kind.IMPORT,
            "knowledge_service_unavailable",
            id="unreachable",
        ),
        pytest.param(
            ClientTimeoutError("slow"),
            TransferJob.Kind.EXPORT,
            "knowledge_service_unavailable",
            id="timeout",
        ),
        pytest.param(
            ClientBadGatewayError("bad"),
            TransferJob.Kind.EXPORT,
            "knowledge_service_unavailable",
            id="bad gateway",
        ),
    ],
)
def test_knowledge_service_failures_name_what_the_creator_can_do(error, kind, code):
    assert public_error(error, kind)["code"] == code


def test_a_project_error_keeps_its_own_code():
    # A cyclic export used to answer `export_cycle_detected` synchronously; a job says the same.
    error = ExportCycleError([(EntityType.GRAPH, 1), (EntityType.GRAPH, 2), (EntityType.GRAPH, 1)])

    assert public_error(error, TransferJob.Kind.EXPORT)["code"] == "export_cycle_detected"


# --- sweep -------------------------------------------------------------------------------


def test_sweep_deletes_old_archives_no_job_owns(store, backend, flow, regular_user, settings):
    settings.TRANSFER_ARCHIVE_TTL = 3600
    now = timezone.now()
    old, young = uuid.uuid4(), uuid.uuid4()
    owned = _export_job(flow, regular_user)
    old_key = store.upload_file(old, IMPORT_ARCHIVE_NAME, io.BytesIO(b"orphan"))
    young_key = store.upload_file(young, IMPORT_ARCHIVE_NAME, io.BytesIO(b"in flight"))
    owned_key = store.upload_file(owned.id, EXPORT_ARCHIVE_NAME, io.BytesIO(b"owned"))
    TransferJob.objects.filter(pk=owned.pk).update(expires_at=now + timedelta(hours=1))
    for key in (old_key, owned_key):
        backend.modified[key] = now - timedelta(hours=2)

    counts = sweep_transfer_jobs(now, store=store)

    assert counts["orphans_deleted"] == 1
    # An upload whose job row is still being created is young; a job's own archive stays.
    assert set(backend.objects) == {young_key, owned_key}


def test_sweep_deletes_a_bounded_number_of_orphans(store, backend, monkeypatch, settings):
    settings.TRANSFER_ARCHIVE_TTL = 3600
    monkeypatch.setattr(runner_module, "MAX_ORPHANED_ARCHIVES_PER_SWEEP", 2)
    now = timezone.now()
    for _ in range(3):
        key = store.upload_file(uuid.uuid4(), IMPORT_ARCHIVE_NAME, io.BytesIO(b"orphan"))
        backend.modified[key] = now - timedelta(hours=2)

    assert sweep_transfer_jobs(now, store=store)["orphans_deleted"] == 2
    assert len(backend.objects) == 1


def test_sweep_deletes_expired_jobs_with_their_archives(store, backend, flow, regular_user):
    now = timezone.now()
    expired = _export_job(flow, regular_user)
    kept = _export_job(flow, regular_user)
    TransferJob.objects.filter(pk=expired.pk).update(expires_at=now - timedelta(seconds=1))
    TransferJob.objects.filter(pk=kept.pk).update(expires_at=now + timedelta(hours=1))
    store.upload_file(expired.id, EXPORT_ARCHIVE_NAME, io.BytesIO(b"old"))
    kept_key = store.upload_file(kept.id, EXPORT_ARCHIVE_NAME, io.BytesIO(b"new"))

    counts = sweep_transfer_jobs(now, store=store)

    assert counts["deleted"] == 1
    assert list(TransferJob.objects.values_list("id", flat=True)) == [kept.id]
    assert list(backend.objects) == [kept_key]


def test_sweep_keeps_a_job_whose_archive_could_not_be_deleted(store, flow, regular_user):
    now = timezone.now()
    job = _export_job(flow, regular_user)
    TransferJob.objects.filter(pk=job.pk).update(expires_at=now - timedelta(seconds=1))

    def failing_delete(job_id):
        raise RuntimeError("storage down")

    store.delete_job = failing_delete

    assert sweep_transfer_jobs(now, store=store)["deleted"] == 0
    assert TransferJob.objects.filter(pk=job.pk).exists()


def test_sweep_fails_jobs_left_running(store, flow, regular_user):
    now = timezone.now()
    stale = _export_job(flow, regular_user)
    fresh = _export_job(flow, regular_user)
    TransferJob.objects.filter(pk=stale.pk).update(
        status=TransferJob.Status.RUNNING, started_at=now - timedelta(hours=2, seconds=1)
    )
    TransferJob.objects.filter(pk=fresh.pk).update(
        status=TransferJob.Status.RUNNING, started_at=now - timedelta(hours=1)
    )

    assert sweep_transfer_jobs(now, store=store)["interrupted"] == 1

    stale.refresh_from_db()
    fresh.refresh_from_db()
    assert (stale.status, stale.error["code"]) == (TransferJob.Status.FAILED, "job_interrupted")
    assert fresh.status == TransferJob.Status.RUNNING


def test_deleting_an_organization_removes_its_transfer_archives(
    store, backend, flow, regular_user, monkeypatch
):
    job = _export_job(flow, regular_user)
    store.upload_file(job.id, EXPORT_ARCHIVE_NAME, io.BytesIO(b"archive"))
    monkeypatch.setattr(organization_deletion, "TransferArchiveStore", lambda: store)
    # The org's own files are another cleanup's business.
    monkeypatch.setattr(
        TablesOrganizationDeletion, "_clean_up_external_artifacts", staticmethod(lambda *args: None)
    )

    clean_up = TablesOrganizationDeletion().sweep(flow.org)
    flow.org.delete()
    clean_up()

    assert backend.objects == {}
    assert not TransferJob.objects.filter(pk=job.pk).exists()


def test_sweep_fails_jobs_that_never_started(store, flow, regular_user):
    now = timezone.now()
    lost = _export_job(flow, regular_user)
    waiting = _export_job(flow, regular_user)
    TransferJob.objects.filter(pk=lost.pk).update(created_at=now - timedelta(hours=2, seconds=1))
    TransferJob.objects.filter(pk=waiting.pk).update(created_at=now - timedelta(hours=1))

    assert sweep_transfer_jobs(now, store=store)["not_started"] == 1

    lost.refresh_from_db()
    waiting.refresh_from_db()
    assert (lost.status, lost.error["code"]) == (TransferJob.Status.FAILED, "job_not_started")
    assert waiting.status == TransferJob.Status.QUEUED


# --- consumer ----------------------------------------------------------------------------


class RecordingRunner:
    def __init__(self, fail: bool = False):
        self.job_ids = []
        self._fail = fail

    def run(self, job_id):
        self.job_ids.append(job_id)
        if self._fail:
            raise RuntimeError("runner broke")


@pytest.fixture
def redis_client():
    client = fakeredis.FakeRedis(decode_responses=True)
    yield client
    client.close()


def _pending(redis_client) -> int:
    return redis_client.xpending(TRANSFER_JOB_STREAM, TRANSFER_JOB_CONSUMER_GROUP)["pending"]


@pytest.mark.parametrize("fail", [False, True], ids=["job runs", "job raises"])
def test_consumer_runs_each_enqueued_job_and_acknowledges_it(
    redis_client, flow, regular_user, fail
):
    runner = RecordingRunner(fail=fail)
    consumer = TransferJobConsumer(redis_client, "host-a", runner=runner)
    consumer.start()
    first, second = _export_job(flow, regular_user), _export_job(flow, regular_user)
    enqueue_transfer_job(first, redis_client=redis_client)
    enqueue_transfer_job(second, redis_client=redis_client)

    # One entry per read: a long job must not hold the next one behind it.
    assert consumer.process_new(block_milliseconds=None) == 1
    assert consumer.process_new(block_milliseconds=None) == 1

    assert runner.job_ids == [first.id, second.id]
    assert _pending(redis_client) == 0


def test_consumer_sweeps_when_asked(redis_client):
    sweeps = []
    consumer = TransferJobConsumer(
        redis_client,
        "host-a",
        runner=RecordingRunner(),
        sweep=lambda now: sweeps.append(now) or {"deleted": 0, "interrupted": 0},
    )
    consumer.start()
    redis_client.xadd(TRANSFER_JOB_STREAM, {TRANSFER_JOB_SWEEP_REQUESTED_AT_FIELD: "2026-01-01"})

    consumer.process_new(block_milliseconds=None)

    assert len(sweeps) == 1
    assert _pending(redis_client) == 0
