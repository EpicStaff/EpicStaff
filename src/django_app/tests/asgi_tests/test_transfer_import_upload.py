"""Background import of an export archive through the streamed upload routes: what is
stored and queued, and every refusal leaving no job, no stored archive and no temp file."""

import io
import json
import os
import zipfile

import httpx
import pytest
from django.db import connection
from asgiref.sync import sync_to_async
from django.test import override_settings
from rest_framework_simplejwt.tokens import AccessToken

from rbac.models.enums import Permission, ResourceType
from tables.import_export.archive import ENVELOPE_MEMBER
from tables.import_export.enums import EntityType
from tables.import_export.registry import entity_registry
from tables.import_export.services.export_service import ExportService
from tables.models import Graph, TransferJob
from tables.services.storage_service.upload.admission import get_upload_admission
from tables.services.transfer_jobs import job_service
from tables.services.transfer_jobs.job_service import import_uploads_in_progress
from tables.services.transfer_jobs.archive_store import TransferArchiveStore
from tables.services.trigger_nodes import TRIGGER_NODE_TYPES
from tables.views import transfer_import_upload_view
from tests.helpers import UNRESTRICTED_EXPORT_POLICY
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403
from tests.storage_backend_fake import FakeStorageBackend

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db(transaction=True)]

FLOWS = "/api/graphs/import-jobs/"
COLLECTIONS = "/api/source-collections/import-jobs/"
ALL_FLOWS = Permission.READ | Permission.CREATE | Permission.UPDATE | Permission.USE


@pytest.fixture
def backend(monkeypatch):
    backend = FakeStorageBackend()
    monkeypatch.setattr(
        job_service, "TransferArchiveStore", lambda: TransferArchiveStore(backend=backend)
    )
    return backend


@pytest.fixture
def enqueued(monkeypatch):
    """Job ids handed to the consumer; each must arrive after its job row is committed."""
    ids = []

    def enqueue(job):
        # Inside an open transaction the consumer could look for a row that is not there yet.
        assert not connection.in_atomic_block, "queued before the job row was committed"
        ids.append(job.id)

    monkeypatch.setattr(job_service, "enqueue_transfer_job", enqueue)
    return ids


@pytest.fixture
def temp_files(monkeypatch):
    names = []
    real = transfer_import_upload_view.tempfile.NamedTemporaryFile

    def tracking(*args, **kwargs):
        file = real(*args, **kwargs)
        names.append(file.name)
        return file

    monkeypatch.setattr(transfer_import_upload_view.tempfile, "NamedTemporaryFile", tracking)
    return names


def _envelope(acme) -> dict:
    flow = Graph.objects.create(name="Support", metadata={"nodes": [], "edges": []}, org=acme)
    result = ExportService(entity_registry).export_entities(
        EntityType.GRAPH, [flow.id], policy=UNRESTRICTED_EXPORT_POLICY
    )
    return result.data


def _zip(envelope: dict) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(ENVELOPE_MEMBER, json.dumps(envelope))
    return buffer.getvalue()


def _user(custom_role_user, acme, flows=ALL_FLOWS, knowledge=Permission.READ | Permission.CREATE):
    return custom_role_user(
        acme,
        "importer@example.com",
        {ResourceType.FLOWS: flows, ResourceType.KNOWLEDGE_SOURCES: knowledge},
    )


async def _post(path, user, org, body, query="", headers=None):
    from django_app.asgi import application

    token = await sync_to_async(lambda: str(AccessToken.for_user(user)))()
    all_headers = {"Authorization": f"Bearer {token}", "X-Organization-Id": str(org.id)}
    all_headers.update(headers or {})
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application), base_url="http://test"
    ) as client:
        return await client.post(f"{path}{query}", content=body, headers=all_headers)


async def _no_job_left(backend, temp_files):
    assert not await TransferJob.objects.aexists()
    assert backend.objects == {}
    assert all(not os.path.exists(name) for name in temp_files)


async def test_a_flow_archive_is_stored_under_a_server_built_key_and_queued(
    custom_role_user, acme, backend, enqueued, temp_files
):
    user = await sync_to_async(_user)(custom_role_user, acme)
    body = _zip(await sync_to_async(_envelope)(acme))

    response = await _post(FLOWS, user, acme, body, "?import_labels=false&preserve_uuids=1")

    assert response.status_code == 202, response.text
    job = await TransferJob.objects.aget(pk=response.json()["job_id"])
    assert (job.kind, job.main_entity, job.org_id, job.created_by_id) == (
        "import",
        "Flow",
        acme.id,
        user.id,
    )
    assert job.request == {
        "settings": {"preserve_uuids": True, "replace_existing": False, "import_labels": False}
    }
    assert job.archive_key == f"system/transfers/{job.id}/import.zip"
    assert backend.objects[job.archive_key] == body
    assert enqueued == [job.id]
    assert temp_files and all(not os.path.exists(name) for name in temp_files)


async def test_the_collection_route_refuses_a_flow_archive(
    custom_role_user, acme, backend, enqueued, temp_files
):
    user = await sync_to_async(_user)(custom_role_user, acme)
    body = _zip(await sync_to_async(_envelope)(acme))

    response = await _post(COLLECTIONS, user, acme, body)

    assert response.status_code == 400, response.text
    assert response.json()["code"] == "invalid_file", response.json()
    await _no_job_left(backend, temp_files)


async def test_a_body_that_is_not_a_zip_is_refused(
    custom_role_user, acme, backend, enqueued, temp_files
):
    user = await sync_to_async(_user)(custom_role_user, acme)

    response = await _post(FLOWS, user, acme, b'{"main_entity": "Flow"}')

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_archive", response.json()
    # Refused on its first bytes, pointing at the route plain JSON belongs to.
    assert "import/ endpoint" in response.json()["message"]
    await _no_job_left(backend, temp_files)


async def test_an_empty_body_is_refused(custom_role_user, acme, backend, enqueued, temp_files):
    user = await sync_to_async(_user)(custom_role_user, acme)

    response = await _post(FLOWS, user, acme, b"")

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_archive", response.json()
    await _no_job_left(backend, temp_files)


async def test_an_archive_older_than_version_6_is_sent_to_the_synchronous_import(
    custom_role_user, acme, backend, enqueued, temp_files
):
    user = await sync_to_async(_user)(custom_role_user, acme)
    envelope = await sync_to_async(_envelope)(acme)
    envelope["version"] = 5

    response = await _post(FLOWS, user, acme, _zip(envelope))

    assert response.status_code == 400
    assert response.json()["code"] == "use_sync_import", response.json()
    await _no_job_left(backend, temp_files)


@override_settings(MAX_KNOWLEDGE_ARCHIVE_SIZE=100)
async def test_a_declared_size_past_the_cap_is_refused_before_reading(
    custom_role_user, acme, backend, enqueued, temp_files
):
    user = await sync_to_async(_user)(custom_role_user, acme)

    response = await _post(FLOWS, user, acme, b"PK\x03\x04" + b"x" * 200)

    assert response.status_code == 413
    assert response.json() == {
        "status_code": 413,
        "code": "archive_too_large",
        "message": "The archive is larger than the import size limit.",
    }
    # Refused before the body was read.
    assert temp_files == []
    await _no_job_left(backend, temp_files)


@override_settings(MAX_KNOWLEDGE_ARCHIVE_SIZE=100)
async def test_a_streamed_body_past_the_cap_is_refused_while_reading(
    custom_role_user, acme, backend, enqueued, temp_files
):
    user = await sync_to_async(_user)(custom_role_user, acme)

    async def chunks():
        yield b"PK\x03\x04"
        for _ in range(10):
            yield b"x" * 30

    # No Content-Length: the cap is applied to the bytes as they arrive.

    response = await _post(FLOWS, user, acme, chunks())

    assert response.status_code == 413
    assert response.json()["code"] == "archive_too_large"
    assert temp_files
    await _no_job_left(backend, temp_files)


@pytest.mark.parametrize(
    "path,query",
    [
        (FLOWS, "?bogus=1"),
        (FLOWS, "?replace_existing=true"),
        (FLOWS, "?preserve_uuids=maybe"),
        (COLLECTIONS, "?import_labels=true"),
    ],
)
async def test_invalid_import_settings_are_refused_before_reading(
    custom_role_user, acme, backend, enqueued, temp_files, path, query
):
    user = await sync_to_async(_user)(custom_role_user, acme)

    response = await _post(path, user, acme, b"PK\x03\x04", query)

    assert response.status_code == 400, response.text
    assert temp_files == []
    await _no_job_left(backend, temp_files)


async def test_replacing_flows_needs_update_rights(
    custom_role_user, acme, backend, enqueued, temp_files
):
    user = await sync_to_async(_user)(
        custom_role_user, acme, flows=Permission.READ | Permission.CREATE
    )

    response = await _post(
        FLOWS, user, acme, b"PK\x03\x04", "?preserve_uuids=true&replace_existing=true"
    )

    assert response.status_code == 403
    await _no_job_left(backend, temp_files)


async def test_importing_collections_needs_create_rights(
    custom_role_user, acme, backend, enqueued, temp_files
):
    user = await sync_to_async(_user)(custom_role_user, acme, knowledge=Permission.READ)

    response = await _post(COLLECTIONS, user, acme, b"PK\x03\x04")

    assert response.status_code == 403
    await _no_job_left(backend, temp_files)


async def test_an_org_the_caller_is_not_in_is_refused(
    custom_role_user, acme, beta, backend, enqueued, temp_files
):
    user = await sync_to_async(_user)(custom_role_user, acme)

    response = await _post(FLOWS, user, beta, b"PK\x03\x04")

    assert response.status_code == 403, response.text
    await _no_job_left(backend, temp_files)


async def test_an_anonymous_upload_is_refused(acme, backend, enqueued, temp_files):
    from django_app.asgi import application

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application), base_url="http://test"
    ) as client:
        response = await client.post(FLOWS, content=b"PK\x03\x04")

    assert response.status_code == 401, response.text
    await _no_job_left(backend, temp_files)


async def test_only_post_is_served(custom_role_user, acme, backend, enqueued, temp_files):
    from django_app.asgi import application

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application), base_url="http://test"
    ) as client:
        response = await client.get(FLOWS)

    assert response.status_code == 405, response.text


async def test_the_job_limit_refuses_before_reading(
    custom_role_user, acme, backend, enqueued, temp_files
):
    user = await sync_to_async(_user)(custom_role_user, acme)
    for _ in range(3):
        await TransferJob.objects.acreate(
            org=acme, created_by=user, kind="export", main_entity="Flow"
        )

    response = await _post(FLOWS, user, acme, b"PK\x03\x04")

    assert response.status_code == 429
    assert response.json()["code"] == "too_many_jobs"
    assert temp_files == []
    assert backend.objects == {}


async def test_the_job_limit_checked_again_at_creation_removes_the_stored_archive(
    custom_role_user, acme, backend, enqueued, temp_files, monkeypatch
):
    user = await sync_to_async(_user)(custom_role_user, acme)
    body = _zip(await sync_to_async(_envelope)(acme))
    for _ in range(3):
        await TransferJob.objects.acreate(
            org=acme, created_by=user, kind="export", main_entity="Flow"
        )
    monkeypatch.setattr(job_service.TransferJobService, "check_limits", lambda self, **_: None)

    response = await _post(FLOWS, user, acme, body)

    assert response.status_code == 429
    assert await TransferJob.objects.acount() == 3
    assert backend.objects == {}
    assert all(not os.path.exists(name) for name in temp_files)


async def test_trigger_nodes_need_use_rights_before_anything_is_stored(
    custom_role_user, acme, backend, enqueued, temp_files
):
    user = await sync_to_async(_user)(
        custom_role_user, acme, flows=Permission.READ | Permission.CREATE
    )
    envelope = await sync_to_async(_envelope)(acme)
    envelope["Flow"][0].setdefault("nodes", []).append({"node_type": sorted(TRIGGER_NODE_TYPES)[0]})

    response = await _post(FLOWS, user, acme, _zip(envelope))

    assert response.status_code == 403, response.text
    await _no_job_left(backend, temp_files)


async def test_a_collection_archive_is_stored_and_queued(
    custom_role_user, acme, backend, enqueued, temp_files
):
    from tables.models.knowledge_models import SourceCollection

    user = await sync_to_async(_user)(custom_role_user, acme)

    def collection_envelope():
        collection = SourceCollection.objects.create(collection_name="Handbook", org=acme)
        return (
            ExportService(entity_registry)
            .export_entities(
                EntityType.SOURCE_COLLECTION,
                [collection.collection_id],
                policy=UNRESTRICTED_EXPORT_POLICY,
            )
            .data
        )

    body = _zip(await sync_to_async(collection_envelope)())

    response = await _post(COLLECTIONS, user, acme, body)

    assert response.status_code == 202, response.text
    job = await TransferJob.objects.aget(pk=response.json()["job_id"])
    assert (job.main_entity, job.request) == ("SourceCollection", {"settings": {}})
    assert backend.objects[job.archive_key] == body
    assert enqueued == [job.id]


async def test_a_lost_queue_entry_still_answers_with_the_committed_job(
    custom_role_user, acme, backend, temp_files, monkeypatch
):
    def redis_down(job):
        raise ConnectionError("redis is down")

    monkeypatch.setattr(job_service, "enqueue_transfer_job", redis_down)
    user = await sync_to_async(_user)(custom_role_user, acme)
    body = _zip(await sync_to_async(_envelope)(acme))

    response = await _post(FLOWS, user, acme, body)

    # The job is committed; the sweep fails it as not started, so its archive must stay.
    assert response.status_code == 202, response.text
    job = await TransferJob.objects.aget(pk=response.json()["job_id"])
    assert job.status == TransferJob.Status.QUEUED
    assert backend.objects[job.archive_key] == body


@override_settings(MAX_KNOWLEDGE_ARCHIVE_SIZE=100)
async def test_an_oversized_upload_is_refused_before_the_job_limit_is_counted(
    custom_role_user, acme, backend, enqueued, temp_files, monkeypatch
):
    def limits_must_not_be_counted(self, **_):
        raise AssertionError("the job limit was counted for an upload past the size cap")

    monkeypatch.setattr(job_service.TransferJobService, "check_limits", limits_must_not_be_counted)
    user = await sync_to_async(_user)(custom_role_user, acme)

    response = await _post(FLOWS, user, acme, b"PK\x03\x04" + b"x" * 200)

    assert response.status_code == 413


async def test_an_upload_in_progress_counts_against_the_job_limit(
    custom_role_user, acme, backend, enqueued, temp_files
):
    user = await sync_to_async(_user)(custom_role_user, acme)
    for _ in range(2):
        await TransferJob.objects.acreate(
            org=acme, created_by=user, kind="export", main_entity="Flow"
        )

    # A third slot is taken by an upload still streaming in.
    with import_uploads_in_progress.hold(org_id=acme.id, user_id=user.id):
        response = await _post(FLOWS, user, acme, b"PK\x03\x04")

    assert response.status_code == 429
    assert response.json()["code"] == "too_many_jobs"
    assert temp_files == []


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(b"not a zip", id="refused"),
        pytest.param(None, id="accepted"),
    ],
)
async def test_an_upload_gives_back_its_hold_and_slot_however_it_ends(
    custom_role_user, acme, backend, enqueued, temp_files, body
):
    user = await sync_to_async(_user)(custom_role_user, acme)
    if body is None:
        body = _zip(await sync_to_async(_envelope)(acme))

    await _post(FLOWS, user, acme, body)

    assert import_uploads_in_progress._uploads[(acme.id, user.id)] == 0
    assert get_upload_admission().uploads_of(acme.id) == 0
