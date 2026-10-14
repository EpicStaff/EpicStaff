"""The storage recycle bin leaks nothing across orgs, and no API write reaches its reserved folder.

Another org's entry answers exactly like one that doesn't exist. The trash folder holds
every org's binned objects, so a write that lands there could overwrite or forge them.
"""

from unittest.mock import patch

import pytest
from django.db.models import Max
from rest_framework import status

from tables.models import StorageFile
from tables.services.storage_service.manager import StorageManager
from tables.services.storage_service.upload import archive_upload, file_upload
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403
from tests.storage_tests.in_memory_backend import InMemoryStorageBackend, seed_file
from tests.storage_tests.storage_writes import stream_upload

BIN = "/api/storage/recycle-bin/"
RESERVED_MESSAGE = "'.recycle-bin' is a reserved folder name."
TRASH_PATHS = [".recycle-bin", ".recycle-bin/x", "/.recycle-bin/x", "a/../.recycle-bin", "a/../.recycle-bin/x"]


@pytest.fixture
def backend():
    return InMemoryStorageBackend(organization_prefix="")


@pytest.fixture
def manager(backend):
    storage_manager = StorageManager(backend)
    with patch("tables.views.storage_views.get_storage_manager", return_value=storage_manager):
        yield storage_manager


@pytest.fixture
def admin_client(client_as, admin_acme, acme):
    client = client_as(admin_acme)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
    return client


def _binned(manager, org, path) -> StorageFile:
    seed_file(manager._backend, org.id, path, b"x")
    manager.delete(org.id, path, user=None)
    return StorageFile.deleted_objects.get(org=org, path=path)


def _missing_id() -> int:
    return (StorageFile.all_objects.aggregate(highest=Max("pk"))["highest"] or 0) + 1000


def _keys(backend) -> set[str]:
    return set(backend._objects)


def _trash_keys(backend, org) -> set[str]:
    return {key for key in backend._objects if key.startswith(f"org_{org.id}/.recycle-bin")}


def _assert_reserved(response) -> None:
    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
    assert RESERVED_MESSAGE in response.content.decode(), response.content


def _assert_nothing_written(backend, org, keys_before: set[str]) -> None:
    assert _keys(backend) == keys_before
    assert not StorageFile.all_objects.filter(org=org, path__contains=".recycle-bin").exists()


@pytest.mark.django_db
class TestForeignEntryLooksMissing:
    def test_restore_answers_alike_for_a_foreign_and_a_missing_id(self, admin_client, manager, beta):
        theirs = _binned(manager, beta, "theirs.txt")

        foreign = admin_client.post(f"{BIN}restore/", {"ids": [theirs.pk]}, format="json")
        missing = admin_client.post(f"{BIN}restore/", {"ids": [_missing_id()]}, format="json")

        assert foreign.status_code == missing.status_code == status.HTTP_404_NOT_FOUND
        assert foreign.json() == missing.json()
        assert StorageFile.deleted_objects.filter(pk=theirs.pk).exists()

    def test_contents_answer_alike_for_a_foreign_and_a_missing_id(self, admin_client, manager, beta):
        seed_file(manager._backend, beta.id, "docs/a.txt", b"a")
        manager.delete(beta.id, "docs", user=None)
        theirs = StorageFile.deleted_objects.get(org=beta, path="docs/")

        foreign = admin_client.get(f"{BIN}{theirs.pk}/contents/")
        missing = admin_client.get(f"{BIN}{_missing_id()}/contents/")

        assert foreign.status_code == missing.status_code == status.HTTP_404_NOT_FOUND
        assert foreign.json() == missing.json()

    def test_a_superadmin_restores_only_in_the_active_org(self, superadmin_in_acme, manager, beta):
        theirs = _binned(manager, beta, "theirs.txt")

        response = superadmin_in_acme.post(f"{BIN}restore/", {"ids": [theirs.pk]}, format="json")

        assert response.status_code == status.HTTP_404_NOT_FOUND, response.content
        assert StorageFile.deleted_objects.filter(pk=theirs.pk).exists()


@pytest.mark.django_db
class TestNoWriteReachesTheTrashFolder:
    @pytest.mark.parametrize("path", TRASH_PATHS)
    def test_mkdir(self, admin_client, manager, backend, acme, path):
        keys_before = _keys(backend)

        response = admin_client.post("/api/storage/mkdir/", {"path": path}, format="json")

        _assert_reserved(response)
        _assert_nothing_written(backend, acme, keys_before)

    @pytest.mark.parametrize("path", TRASH_PATHS)
    def test_rename_into_it(self, admin_client, manager, backend, acme, path):
        seed_file(backend, acme.id, "a.txt", b"a")
        keys_before = _keys(backend)

        response = admin_client.post(
            "/api/storage/rename/", {"from_path": "a.txt", "to_path": f"{path}/a.txt"}, format="json"
        )

        _assert_reserved(response)
        _assert_nothing_written(backend, acme, keys_before)
        assert StorageFile.objects.filter(org=acme, path="a.txt").exists()

    @pytest.mark.parametrize("action", ["move", "copy"])
    @pytest.mark.parametrize("path", TRASH_PATHS)
    def test_move_and_copy_into_it(self, admin_client, manager, backend, acme, action, path):
        seed_file(backend, acme.id, "a.txt", b"a")
        keys_before = _keys(backend)

        response = admin_client.post(
            f"/api/storage/{action}/", {"from_path": "a.txt", "to_path": path}, format="json"
        )

        _assert_reserved(response)
        _assert_nothing_written(backend, acme, keys_before)
        assert StorageFile.objects.filter(org=acme, path="a.txt").exists()

    @pytest.mark.parametrize("action", ["move", "copy"])
    def test_a_superadmin_cannot_move_or_copy_into_another_orgs_trash(
        self, superadmin_in_acme, manager, backend, acme, beta, action
    ):
        seed_file(backend, acme.id, "a.txt", b"a")
        keys_before = _keys(backend)

        response = superadmin_in_acme.post(
            f"/api/storage/{action}/",
            {
                "from_path": "a.txt",
                "to_path": ".recycle-bin/x",
                "source_org_id": acme.id,
                "destination_org_id": beta.id,
            },
            format="json",
        )

        _assert_reserved(response)
        _assert_nothing_written(backend, beta, keys_before)
        assert StorageFile.objects.filter(org=acme, path="a.txt").exists()

    @pytest.mark.parametrize("path", [".recycle-bin/x.txt", "a/../.recycle-bin/x.txt"])
    def test_rename_out_of_it(self, admin_client, manager, backend, acme, path):
        seed_file(backend, acme.id, "a.txt", b"a")
        manager.delete(acme.id, "a.txt", user=None)
        keys_before = _keys(backend)

        response = admin_client.post(
            "/api/storage/rename/", {"from_path": path, "to_path": "stolen.txt"}, format="json"
        )

        _assert_reserved(response)
        assert _keys(backend) == keys_before
        assert not StorageFile.objects.filter(org=acme, path="stolen.txt").exists()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_an_upload_into_the_trash_folder_is_400_and_writes_nothing(org_user, monkeypatch, settings):
    backend = InMemoryStorageBackend(organization_prefix="")
    settings.ORG_STORAGE_QUOTA = 10**9
    settings.MAX_STREAM_UPLOAD_FILE_SIZE = None
    monkeypatch.setattr(file_upload, "get_storage_backend", lambda **_: backend)
    monkeypatch.setattr(archive_upload, "get_storage_backend", lambda **_: backend)
    org = org_user.org

    for path in (".recycle-bin", "a/../.recycle-bin"):
        response = await stream_upload(org_user.user, org, path, "x.txt", b"payload")

        assert response.status_code == status.HTTP_400_BAD_REQUEST, (path, response.text)
        assert RESERVED_MESSAGE in response.text, (path, response.text)
    assert backend._objects == {}
    assert not await StorageFile.all_objects.filter(org=org).aexists()
