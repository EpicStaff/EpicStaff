"""A service account's upload through the stream app, which runs outside Django's middleware."""

import httpx
import pytest
from asgiref.sync import sync_to_async
from django.contrib.contenttypes.models import ContentType
from django.test import override_settings
from plugins.identity.service_account_authentication import PluginServiceAccountAuthentication
from plugins.models import PluginActivityEvent, PluginOwnedResource
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory
from tables.models import StorageFile
from tables.services.storage_service.upload import admission, archive_upload, file_upload
from tables.views.storage_bin_purge_access import StorageBinPurgeAccess
from tables.views.storage_upload_stream_view import UPLOAD_STREAM_PATH

from tests.plugins_tests.conftest import GATEWAY_SECRET
from tests.plugins_tests.package_builder import WEATHER_LIMITS
from tests.storage_tests.in_memory_backend import InMemoryStorageBackend, zip_bytes

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db(transaction=True)]

FILES_CREATE = [{"resource_type": "files", "actions": ["read", "create"], "reason": "Stores files."}]
FILES_READ = [{"resource_type": "files", "actions": ["read"], "reason": "Reads files."}]


@pytest.fixture(autouse=True)
def in_memory_storage(monkeypatch):
    backend = InMemoryStorageBackend(organization_prefix="")
    monkeypatch.setattr(file_upload, "get_storage_backend", lambda **_: backend)
    monkeypatch.setattr(archive_upload, "get_storage_backend", lambda **_: backend)
    monkeypatch.setattr(admission, "_admission", None)
    return backend


def _client():
    from django_app.asgi import application

    return httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url="http://test")


async def _upload(raw_key, organization, query, body):
    async with _client() as client:
        return await client.post(
            f"{UPLOAD_STREAM_PATH}?{query}",
            content=body,
            headers={
                "Authorization": f"PluginKey {raw_key}",
                "X-Plugin-Network-Secret": GATEWAY_SECRET,
                "X-Organization-Id": str(organization.pk),
            },
        )


@pytest.fixture
def key_for(weather_backend, service_account_key, acme):
    @sync_to_async
    def _make(access, **manifest_changes):
        plugin = weather_backend(access=access, **manifest_changes)
        return service_account_key(plugin, acme)

    return _make


@sync_to_async
def _owned_file_paths(organization):
    content_type = ContentType.objects.get_for_model(StorageFile)
    owned_ids = PluginOwnedResource.objects.filter(content_type=content_type).values_list("object_id", flat=True)
    return sorted(StorageFile.objects.filter(org=organization, pk__in=owned_ids).values_list("path", flat=True))


@override_settings(ORG_STORAGE_QUOTA=10**9, MAX_STREAM_UPLOAD_FILE_SIZE=None)
async def test_an_upload_with_files_create_is_stored_owned_and_recorded(key_for, acme):
    raw_key = await key_for(FILES_CREATE)

    response = await _upload(raw_key, acme, "path=weather&filename=README.md", b"# Weather")

    assert response.status_code == 200, response.text
    assert await _owned_file_paths(acme) == ["weather/README.md"]
    event = await PluginActivityEvent.objects.aget(action="api_request")
    assert (event.request_method, event.request_path, event.request_route, event.response_status) == (
        "POST",
        UPLOAD_STREAM_PATH,
        UPLOAD_STREAM_PATH.lstrip("/"),
        200,
    )
    file_row = await StorageFile.objects.aget(org=acme, path="weather/README.md")
    assert (event.target_resource_type, event.target_id, event.target_label) == ("files", str(file_row.pk), "README.md")
    assert event.detail == {"created_count": 1}


@override_settings(ORG_STORAGE_QUOTA=10**9)
async def test_an_archive_owns_its_files_and_none_of_its_folders(key_for, acme):
    raw_key = await key_for(FILES_CREATE)

    response = await _upload(raw_key, acme, "filename=bundle.zip", zip_bytes({"a.txt": b"a", "sub/b.txt": b"b"}))

    assert response.status_code == 200, response.text
    assert await _owned_file_paths(acme) == ["bundle/a.txt", "bundle/sub/b.txt"]


@override_settings(ORG_STORAGE_QUOTA=10**9)
async def test_an_upload_without_files_create_is_refused(key_for, acme):
    raw_key = await key_for(FILES_READ)

    response = await _upload(raw_key, acme, "filename=note.txt", b"x")

    assert response.status_code == 403
    assert not await StorageFile.objects.filter(org=acme).aexists()
    assert not await PluginActivityEvent.objects.filter(action="api_request").aexists()


@override_settings(ORG_STORAGE_QUOTA=10**9, MAX_STREAM_UPLOAD_FILE_SIZE=None)
async def test_the_request_rate_covers_the_upload_stream(key_for, acme):
    raw_key = await key_for(FILES_CREATE, limits={**WEATHER_LIMITS, "requests_per_minute": 1})

    first = await _upload(raw_key, acme, "filename=one.txt", b"1")
    second = await _upload(raw_key, acme, "filename=two.txt", b"2")

    assert (first.status_code, second.status_code) == (200, 429)
    assert second.json()["code"] == "throttled"


async def test_a_service_account_never_purges_the_bin(key_for, acme):
    raw_key = await key_for(FILES_CREATE)

    @sync_to_async
    def _access():
        request = Request(
            APIRequestFactory().post(
                "/", HTTP_AUTHORIZATION=f"PluginKey {raw_key}", HTTP_X_PLUGIN_NETWORK_SECRET=GATEWAY_SECRET
            ),
            authenticators=[PluginServiceAccountAuthentication()],
        )
        assert request.user.plugin_identifier == "weather"
        return StorageBinPurgeAccess.for_request(request, acme.pk)

    access = await _access()

    assert (access.grant, access.names_visible) == (None, False)
