import asyncio
import io
import json
import lzma
import tarfile
from datetime import timedelta
from unittest.mock import AsyncMock

import httpx
import pytest
from asgiref.sync import sync_to_async
from django.core import signals
from django.test import override_settings
from django.utils import timezone
from rest_framework_simplejwt.tokens import AccessToken

from rbac.models import OrganizationUser, Role, RolePermission
from rbac.models.enums import Permission, ResourceType
from tables.views.storage_upload_stream_view import UPLOAD_STREAM_PATH
from tables.models import StorageFile
from tables.services.storage_service import upload as upload_service
from tables.services.storage_service.base import StorageUnreachable
from tables.services.storage_service.manager import StorageManager
from tables.services.storage_service.path_utils import trash_batch_prefix
from tables.services.storage_service.upload import admission as admission_module
from tables.services.storage_service.upload import archive_upload, file_upload
from tables.services.storage_service.upload.admission import UploadAdmission
from tests.storage_tests.in_memory_backend import (
    FakeS3Client,
    InMemoryStorageBackend,
    make_s3_backend,
    seed_file,
    zip_bytes,
)
from utils import exception_handler

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db(transaction=True)]


@sync_to_async
def _token(org_user) -> str:
    return str(AccessToken.for_user(org_user.user))


def _client():
    from django_app.asgi import application

    return httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url="http://test")


async def _post(client, query, *, token=None, org_id=None, body=b"x", headers=None):
    all_headers = dict(headers or {})
    if token:
        all_headers["Authorization"] = f"Bearer {token}"
    if org_id is not None:
        all_headers["X-Organization-Id"] = str(org_id)
    return await client.post(
        f"{UPLOAD_STREAM_PATH}?{query}", content=body, headers=all_headers
    )


@pytest.fixture
def storage(monkeypatch, fake_backend):
    """The in-memory store every upload in the test goes to."""
    monkeypatch.setattr(file_upload, "get_storage_backend", lambda **_: fake_backend)
    monkeypatch.setattr(archive_upload, "get_storage_backend", lambda **_: fake_backend)
    return fake_backend


@pytest.fixture
def stubbed_upload(monkeypatch):
    upload = AsyncMock(return_value={"path": "a.txt", "size": 1, "recycle_bin_purged": []})
    monkeypatch.setattr(upload_service, "upload_file", upload)
    return upload


# --- happy paths ------------------------------------------------------------------


@override_settings(ORG_STORAGE_QUOTA=10**9, MAX_STREAM_UPLOAD_FILE_SIZE=None)
async def test_a_plain_file_is_stored_end_to_end(org_user, storage):
    token = await _token(org_user)
    async with _client() as client:
        response = await _post(
            client,
            "path=docs&filename=note.txt",
            token=token,
            org_id=org_user.org_id,
            body=b"hello streaming world",
        )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "status": "DONE",
        "path": "docs/note.txt",
        "size": 21,
        "recycle_bin_purged": [],
    }
    assert storage._objects[f"org_{org_user.org_id}/docs/note.txt"][0] == b"hello streaming world"
    assert (await StorageFile.objects.aget(org_id=org_user.org_id, path="docs/note.txt")).size == 21


@override_settings(ORG_STORAGE_QUOTA=10**9)
async def test_an_archive_is_unpacked_end_to_end(org_user, storage):
    token = await _token(org_user)
    async with _client() as client:
        response = await _post(
            client,
            "filename=bundle.zip",
            token=token,
            org_id=org_user.org_id,
            body=zip_bytes({"a.txt": b"hello", "sub/b.txt": b"world"}),
        )

    assert response.status_code == 200, response.text
    assert response.json()["path"] == "bundle"
    assert sorted(response.json()["extracted"]) == ["bundle/a.txt", "bundle/sub/b.txt"]
    assert await StorageFile.objects.filter(org_id=org_user.org_id, path="bundle/a.txt").aexists()


@sync_to_async
def _bin_old_file(storage, org_id: int, path: str, size: int) -> str:
    """Store a file, delete it into the bin a day back and return its batch."""
    manager = StorageManager(storage)
    seed_file(storage, org_id, path, b"x" * size)
    batch = manager.delete(org_id, path, user=None)
    StorageFile.deleted_objects.filter(soft_delete_batch=batch).update(
        soft_deleted_at=timezone.now() - timedelta(days=1)
    )
    return batch


def _trash_keys(storage, org_id: int, batch) -> list[str]:
    prefix = trash_batch_prefix(org_id, batch)
    return [key for key in storage._objects if key.startswith(prefix)]


@sync_to_async
def _org_member_with_files_bits(org_id: int, bits: Permission):
    """A member of the org whose custom role grants exactly `bits` on FILES."""
    from django.contrib.auth import get_user_model

    role = Role.objects.create(name=f"Files {int(bits)}", org_id=org_id, is_built_in=False)
    RolePermission.objects.create(
        role=role, resource_type=ResourceType.FILES.value, permissions=int(bits)
    )
    user = get_user_model().objects.create_user(
        email=f"files-{int(bits)}@example.com", password="TestPass123!"
    )
    return OrganizationUser.objects.create(user=user, org_id=org_id, role=role)


async def _binned_paths(org_id: int) -> set[str]:
    return {
        path
        async for path in StorageFile.deleted_objects.filter(org_id=org_id).values_list(
            "path", flat=True
        )
    }


async def test_a_plain_file_past_the_quota_purges_the_bin_and_reports_it(
    org_user, storage, settings
):
    batch = await _bin_old_file(storage, org_user.org_id, "old.txt", 10)
    settings.ORG_STORAGE_QUOTA = 25
    settings.MAX_STREAM_UPLOAD_FILE_SIZE = None
    token = await _token(org_user)
    async with _client() as client:
        response = await _post(
            client, "filename=note.txt", token=token, org_id=org_user.org_id, body=b"y" * 20
        )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "status": "DONE",
        "path": "note.txt",
        "size": 20,
        "recycle_bin_purged": [{"name": "old.txt", "size": 10}],
    }
    assert not await StorageFile.all_objects.filter(org_id=org_user.org_id, path="old.txt").aexists()
    assert _trash_keys(storage, org_user.org_id, batch) == []


async def test_an_archive_past_the_quota_purges_the_bin_and_reports_it(
    org_user, storage, settings
):
    batch = await _bin_old_file(storage, org_user.org_id, "old.txt", 10)
    settings.ORG_STORAGE_QUOTA = 15
    token = await _token(org_user)
    async with _client() as client:
        response = await _post(
            client,
            "filename=bundle.zip",
            token=token,
            org_id=org_user.org_id,
            body=zip_bytes({"a.txt": b"hello", "b.txt": b"world"}),
        )

    assert response.status_code == 200, response.text
    assert response.json()["extracted"] == ["bundle/a.txt", "bundle/b.txt"]
    assert response.json()["recycle_bin_purged"] == [{"name": "old.txt", "size": 10}]
    assert _trash_keys(storage, org_user.org_id, batch) == []


async def test_an_upload_past_the_whole_bin_is_a_413_and_purges_nothing(
    org_user, storage, settings
):
    batch = await _bin_old_file(storage, org_user.org_id, "old.txt", 10)
    settings.ORG_STORAGE_QUOTA = 25
    settings.MAX_STREAM_UPLOAD_FILE_SIZE = None
    token = await _token(org_user)
    async with _client() as client:
        response = await _post(
            client, "filename=note.txt", token=token, org_id=org_user.org_id, body=b"y" * 26
        )

    assert response.status_code == 413
    assert response.json()["code"] == "storage_quota_exceeded"
    assert await StorageFile.deleted_objects.filter(org_id=org_user.org_id, path="old.txt").aexists()
    assert _trash_keys(storage, org_user.org_id, batch) != []


# Each upload fits only once the binned old.txt (10 bytes) is purged.
@pytest.mark.parametrize(
    ("filename", "body", "quota"),
    [
        ("note.txt", b"y" * 20, 25),
        ("bundle.zip", zip_bytes({"a.txt": b"hello", "b.txt": b"world"}), 15),
    ],
    ids=["plain", "archive"],
)
async def test_a_member_without_files_delete_gets_a_413_and_the_bin_stays_whole(
    org_user, storage, settings, filename, body, quota
):
    batch = await _bin_old_file(storage, org_user.org_id, "old.txt", 10)
    settings.ORG_STORAGE_QUOTA = quota
    settings.MAX_STREAM_UPLOAD_FILE_SIZE = None
    # What the built-in Member role holds on FILES: everything but delete.
    member = await _org_member_with_files_bits(
        org_user.org_id,
        Permission.CREATE | Permission.READ | Permission.UPDATE | Permission.EXPORT,
    )
    token = await _token(member)
    async with _client() as client:
        response = await _post(
            client, f"filename={filename}", token=token, org_id=org_user.org_id, body=body
        )

    assert response.status_code == 413, response.text
    assert response.json()["code"] == "storage_quota_exceeded"
    assert await _binned_paths(org_user.org_id) == {"old.txt"}
    assert _trash_keys(storage, org_user.org_id, batch) != []


async def test_an_api_key_gets_a_413_and_the_bin_stays_whole(
    org_user, storage, settings, issue_api_key
):
    batch = await _bin_old_file(storage, org_user.org_id, "old.txt", 10)
    settings.ORG_STORAGE_QUOTA = 25
    settings.MAX_STREAM_UPLOAD_FILE_SIZE = None
    # The key's owner is an Org Admin, who holds FILES:DELETE: the key still may not purge.
    raw_key, _ = await sync_to_async(issue_api_key)(user=org_user.user)
    async with _client() as client:
        response = await _post(
            client,
            "filename=note.txt",
            org_id=org_user.org_id,
            body=b"y" * 20,
            headers={"X-API-Key": raw_key},
        )

    assert response.status_code == 413, response.text
    assert await _binned_paths(org_user.org_id) == {"old.txt"}
    assert _trash_keys(storage, org_user.org_id, batch) != []


async def test_a_caller_without_files_read_gets_the_sizes_but_no_names(
    org_user, storage, settings
):
    await _bin_old_file(storage, org_user.org_id, "old.txt", 10)
    settings.ORG_STORAGE_QUOTA = 25
    settings.MAX_STREAM_UPLOAD_FILE_SIZE = None
    writer = await _org_member_with_files_bits(
        org_user.org_id, Permission.CREATE | Permission.DELETE
    )
    token = await _token(writer)
    async with _client() as client:
        response = await _post(
            client, "filename=note.txt", token=token, org_id=org_user.org_id, body=b"y" * 20
        )

    assert response.status_code == 200, response.text
    assert response.json()["recycle_bin_purged"] == [{"name": None, "size": 10}]
    assert await _binned_paths(org_user.org_id) == set()


# --- auth, RBAC and org scoping ---------------------------------------------------


async def test_an_anonymous_upload_is_a_401_in_the_error_envelope():
    # every DRF view renders {status_code, code, message}; this one must match or
    # the frontend needs a second error parser just for it
    async with _client() as client:
        response = await _post(client, "filename=a.txt")

    assert response.status_code == 401
    assert set(response.json()) == {"status_code", "code", "message"}
    assert response.json()["status_code"] == 401
    assert response.headers["www-authenticate"] == "Bearer"


async def test_a_viewer_without_files_create_is_denied(viewer_org_user):
    token = await _token(viewer_org_user)
    async with _client() as client:
        response = await _post(client, "filename=a.txt", token=token, org_id=viewer_org_user.org_id)

    assert response.status_code == 403
    assert response.json()["code"] == "permission_denied"


async def test_a_non_member_cannot_upload_into_another_org(org_user, second_org, storage):
    token = await _token(org_user)
    async with _client() as client:
        response = await _post(client, "filename=a.txt", token=token, org_id=second_org.id)

    assert response.status_code == 403
    assert not storage._objects


async def test_a_missing_org_header_is_rejected(org_user):
    token = await _token(org_user)
    async with _client() as client:
        response = await _post(client, "filename=a.txt", token=token)

    assert response.status_code == 400


# --- request validation and error rendering ---------------------------------------


async def test_an_executable_name_is_a_400_before_anything_is_stored(org_user, storage):
    token = await _token(org_user)
    async with _client() as client:
        response = await _post(
            client, "filename=evil.exe", token=token, org_id=org_user.org_id, body=b"MZ"
        )

    assert response.status_code == 400
    assert "blocked executable extension" in response.json()["message"]
    assert not storage._objects


async def test_a_non_post_gets_a_json_405():
    async with _client() as client:
        response = await client.get(f"{UPLOAD_STREAM_PATH}?filename=a.txt")

    assert response.status_code == 405
    assert response.json()["status_code"] == 405


@override_settings(CORS_ALLOWED_ORIGINS=["http://localhost:4200"], CORS_ALLOW_CREDENTIALS=True)
@pytest.mark.parametrize(
    ("origin", "allowed"), [("http://localhost:4200", True), ("http://evil.example", False)]
)
async def test_only_an_allowed_origin_gets_cors_headers(org_user, stubbed_upload, origin, allowed):
    # bypassing the middleware chain also bypasses corsheaders, so the handler
    # has to echo the origin itself or a cross-origin frontend cannot read 200s
    token = await _token(org_user)
    async with _client() as client:
        response = await _post(
            client,
            "filename=a.txt",
            token=token,
            org_id=org_user.org_id,
            headers={"Origin": origin},
        )

    assert response.status_code == 200
    if allowed:
        assert response.headers["access-control-allow-origin"] == origin
        assert response.headers["access-control-allow-credentials"] == "true"
    else:
        assert "access-control-allow-origin" not in response.headers


@pytest.mark.parametrize(
    "query", [b"filename=a%FF.txt", b"filename=a\xff.txt"], ids=["escape", "raw"]
)
async def test_a_query_that_is_not_utf8_is_a_400_not_a_mangled_name(
    org_user, stubbed_upload, query
):
    token = await _token(org_user)

    sent = await _call_app(query, token, org_user.org_id, _receive_from())

    status_code, body = _status_and_body(sent)
    assert status_code == 400
    assert "UTF-8" in body["message"]
    stubbed_upload.assert_not_awaited()


async def test_an_unexpected_error_is_a_500_in_the_error_envelope(org_user, monkeypatch):
    # With DEBUG on, custom_exception_handler renders nothing and the error propagates,
    # as from any DRF view; the envelope is what production answers.
    monkeypatch.setattr(exception_handler, "DEBUG", False)
    monkeypatch.setattr(upload_service, "upload_file", AsyncMock(side_effect=RuntimeError("bug")))
    token = await _token(org_user)
    async with _client() as client:
        response = await _post(client, "filename=a.txt", token=token, org_id=org_user.org_id)

    assert response.status_code == 500
    assert response.json() == {
        "status_code": 500,
        "code": "RuntimeError",
        "message": "Unpredictable error",
    }


async def test_request_lifecycle_signals_fire_like_a_django_view(org_user, stubbed_upload):
    # request_finished is what closes stale DB connections; skipping Django's
    # handler must not skip it, on success or on error
    fired = []

    def _started(**_kwargs):
        fired.append("started")

    def _finished(**_kwargs):
        fired.append("finished")

    signals.request_started.connect(_started)
    signals.request_finished.connect(_finished)
    try:
        token = await _token(org_user)
        async with _client() as client:
            ok = await _post(client, "filename=a.txt", token=token, org_id=org_user.org_id)
            denied = await _post(client, "filename=a.txt")
    finally:
        signals.request_started.disconnect(_started)
        signals.request_finished.disconnect(_finished)

    assert (ok.status_code, denied.status_code) == (200, 401)
    assert fired == ["started", "finished", "started", "finished"]


# --- limits, outages and aborted bodies -------------------------------------------


@override_settings(ORG_STORAGE_QUOTA=5 * 1024 * 1024)
async def test_archive_unpacking_past_the_free_space_is_a_413_before_any_write(org_user, storage):
    # the unpacked size has no cap of its own: only the org's free space bounds it
    payload = b"\0" * (6 * 1024 * 1024)
    raw_tar = io.BytesIO()
    with tarfile.open(fileobj=raw_tar, mode="w") as archive:
        info = tarfile.TarInfo(name="big.bin")
        info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))

    token = await _token(org_user)
    async with _client() as client:
        response = await _post(
            client,
            "filename=5-mb-example-file.tar.xz",
            token=token,
            org_id=org_user.org_id,
            body=lzma.compress(raw_tar.getvalue()),
        )

    assert response.status_code == 413
    assert response.json()["code"] == "storage_quota_exceeded"
    assert not storage._objects


async def test_a_full_worker_answers_503_with_retry_after(org_user, monkeypatch):
    admission = UploadAdmission(max_concurrency=1, per_org_limit=5, slot_timeout=0.05)
    monkeypatch.setattr(admission_module, "_admission", admission)
    token = await _token(org_user)

    async with admission.admit(org_id=-1):  # some other org's upload holds the only slot
        async with _client() as client:
            response = await _post(client, "filename=a.txt", token=token, org_id=org_user.org_id)

    assert response.status_code == 503
    assert response.headers["retry-after"] == "1"
    assert response.json()["code"] == "upload_slots_busy"


async def test_an_org_over_its_upload_share_gets_429_with_retry_after(org_user, monkeypatch):
    admission = UploadAdmission(max_concurrency=4, per_org_limit=1, slot_timeout=30)
    monkeypatch.setattr(admission_module, "_admission", admission)
    token = await _token(org_user)

    async with admission.admit(org_user.org_id):
        async with _client() as client:
            response = await _post(client, "filename=a.txt", token=token, org_id=org_user.org_id)

    assert response.status_code == 429
    assert response.headers["retry-after"] == "30"
    assert response.json()["code"] == "org_upload_limit_reached"


@override_settings(ORG_STORAGE_QUOTA=10**9)
async def test_unreachable_storage_is_a_503(org_user, monkeypatch):
    class _StorageDown(InMemoryStorageBackend):
        async def upload_chunks(self, path, chunks, **_kwargs):
            raise StorageUnreachable("storage went away")

    monkeypatch.setattr(file_upload, "get_storage_backend", lambda **_: _StorageDown())
    token = await _token(org_user)
    async with _client() as client:
        response = await _post(client, "filename=a.txt", token=token, org_id=org_user.org_id)

    assert response.status_code == 503
    assert response.headers["retry-after"] == "30"
    assert response.json()["code"] == "storage_unavailable"
    assert not await StorageFile.objects.filter(org_id=org_user.org_id).aexists()


async def _call_app(query: bytes, token: str, org_id: int, receive):
    """Drive the upload ASGI app directly with a hand-written `receive`, for bodies
    and query strings httpx cannot produce (a stall, a disconnect, raw bytes)."""
    from tables.views.storage_upload_stream_view import upload_stream_app

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": UPLOAD_STREAM_PATH,
        "raw_path": UPLOAD_STREAM_PATH.encode(),
        "root_path": "",
        "query_string": query,
        "headers": [
            (b"host", b"test"),
            (b"authorization", f"Bearer {token}".encode()),
            (b"x-organization-id", str(org_id).encode()),
        ],
        "client": ("127.0.0.1", 50000),
        "server": ("test", 80),
    }
    sent = []

    async def _send(message):
        sent.append(message)

    await upload_stream_app(scope, receive, _send)
    return sent


def _receive_from(*events):
    """`receive` returning `events` in order, then hanging like a silent client."""
    pending = list(events)

    async def _receive():
        if pending:
            return pending.pop(0)
        await asyncio.Event().wait()

    return _receive


def _status_and_body(sent) -> tuple[int, dict]:
    start = next(message for message in sent if message["type"] == "http.response.start")
    body = b"".join(
        message.get("body", b"") for message in sent if message["type"] == "http.response.body"
    )
    return start["status"], json.loads(body)


@override_settings(ORG_STORAGE_QUOTA=10**9)
async def test_a_disconnect_mid_body_aborts_the_multipart_upload_and_writes_no_row(
    org_user, monkeypatch
):
    client = FakeS3Client()
    monkeypatch.setattr(file_upload, "get_storage_backend", lambda **_: make_s3_backend(client, part_size=4))
    token = await _token(org_user)

    sent = await _call_app(
        b"filename=a.bin",
        token,
        org_user.org_id,
        _receive_from(
            {"type": "http.request", "body": b"12345678", "more_body": True},
            {"type": "http.disconnect"},
        ),
    )

    assert sent == []  # nobody is left to answer
    assert client.parts and client.aborted and client.completed is None
    assert not await StorageFile.objects.filter(org_id=org_user.org_id).aexists()
    assert admission_module.get_upload_admission().uploads_of(org_user.org_id) == 0


@override_settings(ORG_STORAGE_QUOTA=10**9, UPLOAD_IDLE_TIMEOUT=0.05)
async def test_a_silent_client_gets_408_and_leaves_nothing_behind(org_user, monkeypatch):
    client = FakeS3Client()
    monkeypatch.setattr(file_upload, "get_storage_backend", lambda **_: make_s3_backend(client, part_size=4))
    token = await _token(org_user)

    sent = await _call_app(
        b"filename=a.bin",
        token,
        org_user.org_id,
        _receive_from({"type": "http.request", "body": b"12345678", "more_body": True}),
    )

    status_code, body = _status_and_body(sent)
    assert status_code == 408
    assert body["code"] == "upload_idle_timeout"
    assert client.aborted and client.completed is None
    assert not await StorageFile.objects.filter(org_id=org_user.org_id).aexists()
