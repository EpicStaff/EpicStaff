import io
import lzma
import tarfile
import zipfile
from unittest.mock import AsyncMock

import httpx
import pytest
from asgiref.sync import sync_to_async
from django.conf import settings
from django.test import override_settings
from rest_framework_simplejwt.tokens import AccessToken

from tables.models import StorageFile
from tables.services.storage_service import upload_stream_service as svc
from tests.storage_tests.in_memory_backend import InMemoryStorageBackend


@sync_to_async
def _token(org_user) -> str:
    return str(AccessToken.for_user(org_user.user))


def _client():
    from django_app.asgi import application

    transport = httpx.ASGITransport(app=application)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_stream_upload_happy(org_user, monkeypatch):
    upload = AsyncMock(return_value={"path": "docs/a.txt", "size": 3})
    monkeypatch.setattr(svc, "upload_file", upload)

    token = await _token(org_user)
    async with _client() as client:
        resp = await client.post(
            "/api/storage/upload/stream?path=docs&filename=a.txt",
            content=b"abc",
            headers={
                "Authorization": f"Bearer {token}",
                "X-Organization-Id": str(org_user.org_id),
                "Content-Type": "application/octet-stream",
            },
        )
    assert resp.status_code == 200
    assert resp.json() == {"status": "DONE", "path": "docs/a.txt", "size": 3}
    upload.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_stream_upload_no_token_401():
    async with _client() as client:
        resp = await client.post(
            "/api/storage/upload/stream?filename=a.txt", content=b"abc"
        )
    assert resp.status_code == 401


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_stream_upload_exe_name_400(org_user, monkeypatch):
    # the name is checked by the service, before any of the body is stored
    backend = InMemoryStorageBackend(organization_prefix="")
    monkeypatch.setattr(svc, "_storage_backend", lambda: backend)

    token = await _token(org_user)
    async with _client() as client:
        resp = await client.post(
            "/api/storage/upload/stream?filename=evil.exe",
            content=b"MZ",
            headers={
                "Authorization": f"Bearer {token}",
                "X-Organization-Id": str(org_user.org_id),
            },
        )
    assert resp.status_code == 400
    assert "blocked executable extension" in resp.json()["message"]
    assert not backend._objects


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@override_settings(ORG_STORAGE_QUOTA=10**9, MAX_STREAM_UPLOAD_FILE_SIZE=None)
async def test_stream_upload_end_to_end_flat(org_user, monkeypatch):
    backend = InMemoryStorageBackend(organization_prefix="")
    monkeypatch.setattr(svc, "_storage_backend", lambda: backend)

    token = await _token(org_user)
    async with _client() as client:
        resp = await client.post(
            "/api/storage/upload/stream?path=docs&filename=note.txt",
            content=b"hello streaming world",
            headers={
                "Authorization": f"Bearer {token}",
                "X-Organization-Id": str(org_user.org_id),
            },
        )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"status": "DONE", "path": "docs/note.txt", "size": 21}
    assert backend._objects[f"org_{org_user.org_id}/docs/note.txt"][0] == b"hello streaming world"
    row = await StorageFile.objects.aget(org_id=org_user.org_id, path="docs/note.txt")
    assert row.size == 21


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@override_settings(ORG_STORAGE_QUOTA=10, MAX_STREAM_UPLOAD_FILE_SIZE=None)
async def test_stream_upload_over_quota_413(org_user, monkeypatch):
    backend = InMemoryStorageBackend(organization_prefix="")
    monkeypatch.setattr(svc, "_storage_backend", lambda: backend)

    token = await _token(org_user)
    async with _client() as client:
        resp = await client.post(
            "/api/storage/upload/stream?filename=big.bin",
            content=b"x" * 50,
            headers={
                "Authorization": f"Bearer {token}",
                "X-Organization-Id": str(org_user.org_id),
            },
        )
    assert resp.status_code == 413
    assert not backend._objects
    assert not await StorageFile.objects.filter(org_id=org_user.org_id).aexists()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@override_settings(ORG_STORAGE_QUOTA=10**9, MAX_ARCHIVE_UNCOMPRESSED_SIZE=10**6)
async def test_stream_upload_end_to_end_archive(org_user, monkeypatch):
    backend = InMemoryStorageBackend(organization_prefix="")
    monkeypatch.setattr(svc, "_storage_backend", lambda: backend)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("a.txt", "hello")
        zf.writestr("sub/b.txt", "world")

    token = await _token(org_user)
    async with _client() as client:
        resp = await client.post(
            "/api/storage/upload/stream?filename=bundle.zip",
            content=buf.getvalue(),
            headers={
                "Authorization": f"Bearer {token}",
                "X-Organization-Id": str(org_user.org_id),
            },
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["path"].startswith("bundle-")
    assert len(body["extracted"]) == 2
    assert await StorageFile.objects.filter(
        org_id=org_user.org_id, path=f"{body['path']}/a.txt"
    ).aexists()


async def _post(client, query, *, token=None, org_id=None, body=b"x", headers=None):
    hdrs = dict(headers or {})
    if token:
        hdrs["Authorization"] = f"Bearer {token}"
    if org_id is not None:
        hdrs["X-Organization-Id"] = str(org_id)
    return await client.post(f"/api/storage/upload/stream?{query}", content=body, headers=hdrs)


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_errors_use_the_project_error_envelope(org_user):
    # every DRF view renders {status_code, code, message}; this one must match or
    # the frontend needs a second error parser just for it
    async with _client() as client:
        resp = await _post(client, "filename=a.txt")
    assert resp.status_code == 401
    assert set(resp.json()) == {"status_code", "code", "message"}
    assert resp.json()["status_code"] == 401


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_viewer_without_files_create_is_denied(viewer_org_user):
    token = await _token(viewer_org_user)
    async with _client() as client:
        resp = await _post(client, "filename=a.txt", token=token, org_id=viewer_org_user.org_id)
    assert resp.status_code == 403
    assert resp.json()["code"] == "permission_denied"


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_non_member_cannot_upload_into_another_org(org_user, second_org):
    token = await _token(org_user)
    async with _client() as client:
        resp = await _post(client, "filename=a.txt", token=token, org_id=second_org.id)
    assert resp.status_code == 403


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_missing_org_header_is_rejected(org_user):
    token = await _token(org_user)
    async with _client() as client:
        resp = await _post(client, "filename=a.txt", token=token)
    assert resp.status_code == 400


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_non_post_gets_json_405(org_user):
    async with _client() as client:
        resp = await client.get("/api/storage/upload/stream?filename=a.txt")
    assert resp.status_code == 405
    assert resp.json()["status_code"] == 405


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@override_settings(CORS_ALLOWED_ORIGINS=["http://localhost:4200"], CORS_ALLOW_CREDENTIALS=True)
async def test_allowed_origin_gets_cors_headers(org_user, monkeypatch):
    # bypassing the middleware chain also bypasses corsheaders, so the handler
    # has to echo the origin itself or a cross-origin frontend cannot read 200s
    monkeypatch.setattr(svc, "upload_file", AsyncMock(return_value={"path": "a.txt", "size": 1}))
    token = await _token(org_user)
    async with _client() as client:
        resp = await _post(
            client,
            "filename=a.txt",
            token=token,
            org_id=org_user.org_id,
            headers={"Origin": "http://localhost:4200"},
        )
    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == "http://localhost:4200"
    assert resp.headers["access-control-allow-credentials"] == "true"


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@override_settings(CORS_ALLOWED_ORIGINS=["http://localhost:4200"])
async def test_disallowed_origin_gets_no_cors_headers(org_user, monkeypatch):
    monkeypatch.setattr(svc, "upload_file", AsyncMock(return_value={"path": "a.txt", "size": 1}))
    token = await _token(org_user)
    async with _client() as client:
        resp = await _post(
            client,
            "filename=a.txt",
            token=token,
            org_id=org_user.org_id,
            headers={"Origin": "http://evil.example"},
        )
    assert "access-control-allow-origin" not in resp.headers


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@override_settings(ORG_STORAGE_QUOTA=5 * 1024 * 1024)
async def test_archive_unpacking_past_the_free_space_is_a_413_before_any_write(
    org_user, monkeypatch
):
    # the unpacked size has no cap of its own: only the org's free space bounds it
    backend = InMemoryStorageBackend(organization_prefix="")
    monkeypatch.setattr(svc, "_storage_backend", lambda: backend)

    payload = b"\0" * (6 * 1024 * 1024)
    raw_tar = io.BytesIO()
    with tarfile.open(fileobj=raw_tar, mode="w") as tf:
        info = tarfile.TarInfo(name="big.bin")
        info.size = len(payload)
        tf.addfile(info, io.BytesIO(payload))
    bomb = lzma.compress(raw_tar.getvalue())

    token = await _token(org_user)
    async with _client() as client:
        resp = await _post(
            client,
            "filename=5-mb-example-file.tar.xz",
            token=token,
            org_id=org_user.org_id,
            body=bomb,
        )

    assert resp.status_code == 413
    assert resp.json()["code"] == "storage_quota_exceeded"
    assert not backend._objects


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_bad_utf8_escape_in_query_is_a_400_not_a_mangled_name(org_user, monkeypatch):
    upload = AsyncMock()
    monkeypatch.setattr(svc, "upload_file", upload)
    token = await _token(org_user)
    async with _client() as client:
        resp = await _post(client, "filename=a%FF.txt", token=token, org_id=org_user.org_id)
    assert resp.status_code == 400
    assert "UTF-8" in resp.json()["message"]
    upload.assert_not_awaited()


def test_raw_non_utf8_query_bytes_are_a_validation_error():
    from rest_framework.exceptions import ValidationError

    from tables.asgi_upload import _reject_non_utf8_query

    with pytest.raises(ValidationError):
        _reject_non_utf8_query({"query_string": b"filename=a\xff.txt"})
    _reject_non_utf8_query({"query_string": "filename=док.txt".encode()})


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_request_lifecycle_signals_fire_like_a_django_view(org_user, monkeypatch):
    # request_finished is what closes stale DB connections; skipping Django's
    # handler must not skip it, on success or on error
    from django.core import signals

    monkeypatch.setattr(svc, "upload_file", AsyncMock(return_value={"path": "a.txt", "size": 1}))
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
