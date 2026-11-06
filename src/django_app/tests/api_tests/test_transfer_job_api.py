"""Background export jobs over the API: creating them, the limits on them, reading their
status, downloading their archive, and who may see a job at all."""

import io
import json
import unittest.mock
import uuid
import zipfile

import fakeredis

import pytest
from django.urls import reverse

from rbac.models import OrganizationUser
from rbac.models.enums import Permission, ResourceType
from rbac.models.role import RolePermission
from tables.import_export.archive import ENVELOPE_MEMBER
from tables.import_export.constants import IMPORT_VERSION, MAIN_ENTITY_KEY
from tables.import_export.enums import EntityType
from tables.models import Graph, TransferJob
from tables.models.knowledge_models import SourceCollection
from tables.services.transfer_jobs import job_service
from tables.services.transfer_jobs.archive_store import TransferArchiveStore
from tables.views import transfer_job_views
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403
from tests.storage_backend_fake import FakeStorageBackend

pytestmark = pytest.mark.django_db

FLOW_RIGHTS = {ResourceType.FLOWS: Permission.READ | Permission.CREATE | Permission.EXPORT}
KNOWLEDGE_RIGHTS = {
    ResourceType.KNOWLEDGE_SOURCES: Permission.READ | Permission.CREATE | Permission.EXPORT
}


@pytest.fixture
def enqueued(monkeypatch):
    """Job ids handed to the background consumer, in order."""
    job_ids = []
    monkeypatch.setattr(job_service, "enqueue_transfer_job", lambda job: job_ids.append(job.id))
    return job_ids


@pytest.fixture
def backend(monkeypatch):
    backend = FakeStorageBackend()
    monkeypatch.setattr(
        transfer_job_views, "TransferArchiveStore", lambda: TransferArchiveStore(backend=backend)
    )
    return backend


@pytest.fixture
def exporter(custom_role_user, acme):
    return custom_role_user(acme, "exporter@example.com", {**FLOW_RIGHTS, **KNOWLEDGE_RIGHTS})


@pytest.fixture
def client_in(client_as):
    def _client(user, org):
        client = client_as(user)
        client.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
        return client

    return _client


@pytest.fixture
def flow(acme):
    return Graph.objects.create(name="Support", metadata={"nodes": [], "edges": []}, org=acme)


def _job(user, org, **fields) -> TransferJob:
    return TransferJob.objects.create(
        org=org,
        created_by=user,
        kind=fields.pop("kind", TransferJob.Kind.EXPORT),
        main_entity=fields.pop("main_entity", TransferJob.MainEntity.FLOW),
        **fields,
    )


def _create_flow_job(client, body):
    return client.post(reverse("graphs-export-jobs"), body, format="json")


# --- creating export jobs ------------------------------------------------------------------


def test_a_flow_export_job_is_stored_and_queued_after_commit(
    client_in, exporter, acme, flow, enqueued, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        response = _create_flow_job(
            client_in(exporter, acme), {"ids": [flow.id], "include_knowledge": False}
        )
        # Queued only once the job row is committed.
        assert enqueued == []

    assert response.status_code == 202
    job = TransferJob.objects.get(pk=response.json()["job_id"])
    assert (job.org_id, job.created_by_id, job.kind, job.main_entity, job.status) == (
        acme.id,
        exporter.id,
        TransferJob.Kind.EXPORT,
        TransferJob.MainEntity.FLOW,
        TransferJob.Status.QUEUED,
    )
    # Only validated keys are stored.
    assert job.request == {"ids": [flow.id], "include_knowledge": False}

    for callback in callbacks:
        callback()
    assert enqueued == [job.id]


def test_knowledge_is_included_unless_asked_otherwise(client_in, exporter, acme, flow, enqueued):
    response = _create_flow_job(client_in(exporter, acme), {"ids": [flow.id]})

    assert TransferJob.objects.get(pk=response.json()["job_id"]).request["include_knowledge"]


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"ids": []}, id="no ids"),
        pytest.param({"ids": ["1"]}, id="id as text"),
        pytest.param({"ids": [True]}, id="id as bool"),
        pytest.param({"ids": [0]}, id="zero"),
        pytest.param({"ids": list(range(1, 502))}, id="too many ids"),
        pytest.param({"ids": [1], "include_knowledge": "maybe"}, id="flag not a bool"),
    ],
)
def test_an_invalid_export_request_creates_no_job(client_in, exporter, acme, enqueued, body):
    response = _create_flow_job(client_in(exporter, acme), body)

    assert response.status_code == 400
    # Refused for its shape, before any id is looked up.
    assert response.json()["code"] != "export_entities_not_found"
    assert not TransferJob.objects.exists()
    assert enqueued == []


def test_a_flow_of_another_org_is_not_exported(client_in, exporter, acme, beta, enqueued):
    foreign = Graph.objects.create(name="Theirs", metadata={"nodes": [], "edges": []}, org=beta)

    response = _create_flow_job(client_in(exporter, acme), {"ids": [foreign.id]})

    assert response.status_code == 400
    assert response.json()["code"] == "export_entities_not_found"
    assert not TransferJob.objects.exists()


@pytest.mark.parametrize(
    ("url_name", "rights", "body"),
    [
        pytest.param(
            "graphs-export-jobs",
            {ResourceType.FLOWS: Permission.READ | Permission.CREATE},
            "flow",
            id="flows without export",
        ),
        pytest.param(
            "sourcecollection-export-jobs",
            {ResourceType.KNOWLEDGE_SOURCES: Permission.READ | Permission.CREATE},
            "collection",
            id="knowledge sources without export",
        ),
    ],
)
def test_an_export_job_needs_export_rights(
    client_in, custom_role_user, acme, flow, enqueued, url_name, rights, body
):
    collection = SourceCollection.objects.create(collection_name="Handbook", org=acme)
    user = custom_role_user(acme, "no-export@example.com", rights)
    ids = [flow.id] if body == "flow" else [collection.collection_id]

    response = client_in(user, acme).post(reverse(url_name), {"ids": ids}, format="json")

    assert response.status_code == 403
    assert not TransferJob.objects.exists()


def test_a_collection_export_job_is_queued(client_in, exporter, acme, enqueued):
    collection = SourceCollection.objects.create(collection_name="Handbook", org=acme)

    response = client_in(exporter, acme).post(
        reverse("sourcecollection-export-jobs"), {"ids": [collection.collection_id]}, format="json"
    )

    assert response.status_code == 202
    job = TransferJob.objects.get(pk=response.json()["job_id"])
    assert job.main_entity == TransferJob.MainEntity.SOURCE_COLLECTION
    assert job.request == {"ids": [collection.collection_id]}


# --- limits ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("unfinished", "accepted"),
    [
        pytest.param(2, True, id="two unfinished"),
        pytest.param(3, False, id="three unfinished"),
    ],
)
def test_one_user_may_have_three_unfinished_jobs(
    client_in, exporter, acme, flow, enqueued, unfinished, accepted
):
    statuses = [TransferJob.Status.QUEUED, TransferJob.Status.RUNNING, TransferJob.Status.QUEUED]
    for status in statuses[:unfinished]:
        _job(exporter, acme, status=status)
    # Finished jobs do not count.
    _job(exporter, acme, status=TransferJob.Status.COMPLETED)
    _job(exporter, acme, status=TransferJob.Status.FAILED)

    response = _create_flow_job(client_in(exporter, acme), {"ids": [flow.id]})

    if accepted:
        assert response.status_code == 202
    else:
        assert response.status_code == 429
        assert response.json()["code"] == "too_many_jobs"
        assert TransferJob.objects.count() == unfinished + 2


@pytest.mark.parametrize(("unfinished", "accepted"), [(9, True), (10, False)])
def test_an_org_may_have_ten_unfinished_jobs(
    client_in, exporter, custom_role_user, acme, flow, enqueued, unfinished, accepted
):
    for number in range(unfinished):
        colleague = custom_role_user(acme, f"colleague-{number}@example.com", FLOW_RIGHTS)
        _job(colleague, acme, status=TransferJob.Status.QUEUED)

    response = _create_flow_job(client_in(exporter, acme), {"ids": [flow.id]})

    assert response.status_code == (202 if accepted else 429)


def test_jobs_in_another_org_do_not_count(
    client_in, exporter, custom_role_user, acme, beta, flow, enqueued
):
    for number in range(10):
        stranger = custom_role_user(beta, f"stranger-{number}@example.com", FLOW_RIGHTS)
        _job(stranger, beta, status=TransferJob.Status.QUEUED)

    assert _create_flow_job(client_in(exporter, acme), {"ids": [flow.id]}).status_code == 202


# --- status and visibility -----------------------------------------------------------------


def test_status_shows_the_jobs_outcome(client_in, exporter, acme):
    job = _job(
        exporter,
        acme,
        status=TransferJob.Status.COMPLETED,
        file_name="flow_support.zip",
        result={"excluded": []},
    )

    response = client_in(exporter, acme).get(reverse("transfer-jobs-detail", args=[job.id]))

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "id",
        "kind",
        "main_entity",
        "status",
        "file_name",
        "result",
        "error",
        "created_at",
        "finished_at",
        "expires_at",
    }
    assert (body["status"], body["file_name"], body["result"]) == (
        "completed",
        "flow_support.zip",
        {"excluded": []},
    )


@pytest.mark.parametrize("route", ["transfer-jobs-detail", "transfer-jobs-download"])
@pytest.mark.parametrize(
    "who",
    ["colleague in the same org", "creator in another org"],
)
def test_a_job_is_visible_only_to_its_creator_in_its_org(
    client_in, exporter, custom_role_user, acme, beta, backend, route, who
):
    job = _job(exporter, acme, status=TransferJob.Status.COMPLETED, archive_key="k")
    if who == "colleague in the same org":
        client = client_in(custom_role_user(acme, "colleague@example.com", FLOW_RIGHTS), acme)
    else:
        # The creator is a member of both orgs, but asks with the other org active.
        from rbac.models import OrganizationUser, Role

        role = Role.objects.create(name="beta-flows", org=beta, is_built_in=False)
        OrganizationUser.objects.create(user=exporter, org=beta, role=role)
        client = client_in(exporter, beta)

    response = client.get(reverse(route, args=[job.id]))

    assert response.status_code == 404


@pytest.mark.parametrize("job_id", ["not-a-uuid", str(uuid.uuid4())])
def test_an_unknown_job_is_not_found(client_in, exporter, acme, job_id):
    response = client_in(exporter, acme).get(f"/api/transfer-jobs/{job_id}/")

    assert response.status_code == 404


# --- download -------------------------------------------------------------------------------


def test_a_completed_export_downloads_as_a_zip_stream(client_in, exporter, acme, backend):
    archive = bytes(range(256)) * 9000  # more than one 1 MiB chunk
    job = _job(
        exporter,
        acme,
        status=TransferJob.Status.COMPLETED,
        file_name="flow_support.zip",
    )
    job.archive_key = TransferArchiveStore(backend=backend).upload_file(
        job.id, "export.zip", io.BytesIO(archive)
    )
    job.save(update_fields=["archive_key"])

    response = client_in(exporter, acme).get(reverse("transfer-jobs-download", args=[job.id]))

    assert response.status_code == 200
    assert response.streaming
    assert response["Content-Type"] == "application/zip"
    assert 'filename="flow_support.zip"' in response["Content-Disposition"]
    assert b"".join(response.streaming_content) == archive


@pytest.mark.parametrize(
    "fields",
    [
        pytest.param({"status": TransferJob.Status.QUEUED}, id="queued export"),
        pytest.param({"status": TransferJob.Status.FAILED}, id="failed export"),
        pytest.param(
            {"status": TransferJob.Status.COMPLETED, "kind": TransferJob.Kind.IMPORT},
            id="completed import",
        ),
    ],
)
def test_only_a_completed_export_can_be_downloaded(client_in, exporter, acme, backend, fields):
    job = _job(exporter, acme, archive_key="k", **fields)

    response = client_in(exporter, acme).get(reverse("transfer-jobs-download", args=[job.id]))

    assert response.status_code == 409
    assert response.json()["code"] == "job_not_ready"


def test_download_needs_export_rights_at_download_time(client_in, exporter, acme, backend):
    job = _job(exporter, acme, status=TransferJob.Status.COMPLETED, archive_key="k")
    from rbac.models.role import RolePermission

    RolePermission.objects.filter(
        role__organization_users__user=exporter, resource_type=ResourceType.FLOWS
    ).update(permissions=int(Permission.READ))

    response = client_in(exporter, acme).get(reverse("transfer-jobs-download", args=[job.id]))

    assert response.status_code == 403


def test_a_missing_archive_is_not_found(client_in, exporter, acme, backend):
    job = _job(
        exporter,
        acme,
        status=TransferJob.Status.COMPLETED,
        archive_key="system/transfers/gone/export.zip",
    )

    response = client_in(exporter, acme).get(reverse("transfer-jobs-download", args=[job.id]))

    assert response.status_code == 404


# --- API keys and the removed synchronous export --------------------------------------------


def test_a_personal_api_key_creates_and_reads_its_owners_job(
    api_client, regular_user, default_org, issue_api_key, enqueued
):
    flow = Graph.objects.create(name="Mine", metadata={"nodes": [], "edges": []}, org=default_org)
    raw_key, _key = issue_api_key(user=regular_user, org=default_org)
    api_client.credentials(HTTP_X_API_KEY=raw_key)

    created = _create_flow_job(api_client, {"ids": [flow.id]})
    status = api_client.get(reverse("transfer-jobs-detail", args=[created.json()["job_id"]]))

    assert created.status_code == 202
    assert TransferJob.objects.get().created_by_id == regular_user.id
    assert status.status_code == 200


def test_a_system_api_key_cannot_own_a_job(api_client, default_org, env_api_key, enqueued):
    flow = Graph.objects.create(name="Mine", metadata={"nodes": [], "edges": []}, org=default_org)
    raw_key, _key = env_api_key
    api_client.credentials(HTTP_X_API_KEY=raw_key, HTTP_X_ORGANIZATION_ID=str(default_org.id))

    response = _create_flow_job(api_client, {"ids": [flow.id]})

    assert response.status_code == 403
    assert not TransferJob.objects.exists()


def test_the_synchronous_flow_export_is_gone(client_in, exporter, acme, flow):
    client = client_in(exporter, acme)

    single = client.get(f"/api/graphs/{flow.id}/export/")
    bulk = client.post("/api/graphs/bulk-export/", {"ids": [flow.id]}, format="json")

    assert single.status_code == 404
    # Read as the detail route of a flow called "bulk-export": refused, never served.
    assert bulk.status_code in {403, 404, 405}


# --- inspecting a collection archive ---------------------------------------------------------


def test_a_collection_archive_can_be_inspected(client_in, exporter, acme):
    upload = io.BytesIO()
    with zipfile.ZipFile(upload, "w") as archive:
        archive.writestr(
            ENVELOPE_MEMBER,
            json.dumps({MAIN_ENTITY_KEY: EntityType.SOURCE_COLLECTION, "version": IMPORT_VERSION}),
        )
    upload.seek(0)
    upload.name = "collections.zip"

    response = client_in(exporter, acme).post(
        reverse("sourcecollection-inspect-import"), {"file": upload}, format="multipart"
    )

    assert response.status_code == 200
    assert response.json() == {"review_items": []}


# --- one-time download tickets --------------------------------------------------------------


@pytest.fixture
def fake_redis():
    fake = fakeredis.FakeStrictRedis()
    with unittest.mock.patch("rbac.identity.tickets.get_redis_connection", return_value=fake):
        yield fake


@pytest.fixture
def stored_export(exporter, acme, backend):
    """A completed export of `exporter` in acme, with its archive in storage."""
    job = _job(exporter, acme, status=TransferJob.Status.COMPLETED, file_name="flow_support.zip")
    job.archive_key = TransferArchiveStore(backend=backend).upload_file(
        job.id, "export.zip", io.BytesIO(b"zip bytes")
    )
    job.save(update_fields=["archive_key"])
    return job


def _issue_ticket(client, job) -> str:
    response = client.post(reverse("transfer-jobs-download-ticket", args=[job.id]))
    assert response.status_code == 200, response.content
    return response.json()["download_url"]


def test_a_ticket_downloads_once_without_any_credentials(
    client_in, exporter, acme, stored_export, fake_redis, api_client
):
    url = _issue_ticket(client_in(exporter, acme), stored_export)
    assert url.startswith(f"/api/transfer-jobs/{stored_export.id}/download/?ticket=")

    # A browser navigation: no Authorization header, no org header.
    first = api_client.get(url)
    second = api_client.get(url)

    assert first.status_code == 200
    assert b"".join(first.streaming_content) == b"zip bytes"
    assert second.status_code == 404


@pytest.mark.parametrize(
    "ticket_url",
    [
        pytest.param(lambda job, url: url.replace("ticket=", "ticket=x"), id="unknown ticket"),
        pytest.param(
            lambda job, url: url.replace(str(job.id), str(uuid.uuid4())), id="another job's url"
        ),
    ],
)
def test_a_ticket_opens_only_its_own_job(
    client_in, exporter, acme, stored_export, fake_redis, api_client, ticket_url
):
    url = _issue_ticket(client_in(exporter, acme), stored_export)

    assert api_client.get(ticket_url(stored_export, url)).status_code == 404
    # The failed attempt did not spend the real ticket.
    assert api_client.get(url).status_code == 200


def test_an_expired_ticket_is_refused(
    client_in, exporter, acme, stored_export, fake_redis, api_client
):
    url = _issue_ticket(client_in(exporter, acme), stored_export)
    for key in fake_redis.scan_iter("rbac:transfer_download_ticket:*"):
        assert 0 < fake_redis.ttl(key) <= 60
        fake_redis.delete(key)  # what expiry does

    assert api_client.get(url).status_code == 404


def test_a_ticket_is_issued_only_to_the_jobs_creator(
    client_in, custom_role_user, acme, stored_export, fake_redis
):
    colleague = custom_role_user(acme, "colleague@example.com", FLOW_RIGHTS)

    response = client_in(colleague, acme).post(
        reverse("transfer-jobs-download-ticket", args=[stored_export.id])
    )

    assert response.status_code == 404


def test_no_ticket_for_an_unfinished_export(client_in, exporter, acme, backend, fake_redis):
    job = _job(exporter, acme, status=TransferJob.Status.RUNNING)

    response = client_in(exporter, acme).post(
        reverse("transfer-jobs-download-ticket", args=[job.id])
    )

    assert response.status_code == 409
    assert response.json()["code"] == "job_not_ready"


@pytest.mark.parametrize(
    ("change", "status"),
    [
        pytest.param("export revoked", 403, id="export right revoked"),
        pytest.param("left the org", 404, id="no longer a member"),
        pytest.param("deactivated", 404, id="account deactivated"),
    ],
)
def test_a_ticket_rechecks_the_holder_when_it_is_used(
    client_in, exporter, acme, stored_export, fake_redis, api_client, change, status
):
    url = _issue_ticket(client_in(exporter, acme), stored_export)
    if change == "export revoked":
        RolePermission.objects.filter(
            role__organization_users__user=exporter, resource_type=ResourceType.FLOWS
        ).update(permissions=int(Permission.READ))
    elif change == "left the org":
        OrganizationUser.objects.filter(user=exporter, org=acme).delete()
    else:
        exporter.is_active = False
        exporter.save(update_fields=["is_active"])

    assert api_client.get(url).status_code == status


def test_a_download_without_ticket_or_credentials_is_refused(stored_export, api_client):
    response = api_client.get(reverse("transfer-jobs-download", args=[stored_export.id]))

    assert response.status_code == 401
