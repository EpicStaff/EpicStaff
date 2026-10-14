"""The storage recycle bin leaks nothing across orgs, and no API write reaches its reserved folder.

Another org's entry answers exactly like one that doesn't exist. The trash folder holds
every org's binned objects, so a write that lands there could overwrite or forge them. A
purge never takes another org's row with it (a flow of another org linked to the file).
"""

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.db import transaction
from django.db.models import Max
from django.utils import timezone
from rest_framework import status

from tables.exceptions import CrossOrgCascadeError, StorageQuotaExceeded
from tables.models import Graph, GraphStorageFile, StorageFile
from tables.services.recycle_bin.purge_service import PurgeService
from tables.services.storage_service.dataclasses import PurgedBinEntry
from tables.services.storage_service.manager import StorageManager
from tables.services.storage_service.recycle_bin import StorageRecycleBinService
from tables.services.storage_service.upload import archive_upload, file_upload
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403
from tests.storage_tests.in_memory_backend import InMemoryStorageBackend, seed_file
from tests.storage_tests.storage_writes import stream_upload
from utils.logger import logger

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


def _binned_days_ago(manager, org, path: str, size: int, days_ago: int) -> StorageFile:
    seed_file(manager._backend, org.id, path, b"x" * size)
    batch = manager.delete(org.id, path, user=None)
    StorageFile.deleted_objects.filter(org=org, soft_delete_batch=batch).update(
        soft_deleted_at=timezone.now() - timedelta(days=days_ago)
    )
    return StorageFile.deleted_objects.get(org=org, path=path)


def _linked_to_a_flow_of(org, row: StorageFile) -> GraphStorageFile:
    """Link `row` to a flow of `org` straight in the database: the API refuses a cross-org link."""
    graph = Graph.objects.create(org=org, name=f"Flow of {org.name} using {row.path}")
    return GraphStorageFile.objects.create(graph=graph, storage_file=row)


def _refusal_line(description: str, org, link: GraphStorageFile, other_org) -> str:
    return (
        f"Refused to delete {description} of org {org.id}: the delete reaches "
        f"GraphStorageFile {link.pk} of org(s) [{other_org.id}], "
        "linked across organizations outside the API\n"
    )


@pytest.fixture
def error_log():
    messages: list[str] = []
    sink_id = logger.add(messages.append, level="ERROR", format="{message}")
    yield messages
    logger.remove(sink_id)


@pytest.mark.django_db
class TestPurgeNeverReachesAnotherOrg:
    """GraphStorageFile cascades from StorageFile, so purging a file linked to another
    org's flow would delete that org's link row. Each purge refuses such an entry, keeps it
    in the bin with its trash objects, and goes on with the rest."""

    def test_a_bulk_purge_reports_the_linked_file_and_purges_the_rest(
        self, superadmin_in_acme, manager, backend, acme, beta
    ):
        linked = _binned(manager, acme, "linked.txt")
        plain = _binned(manager, acme, "plain.txt")
        link = _linked_to_a_flow_of(beta, linked)

        response = superadmin_in_acme.post(f"{BIN}purge/", {"ids": [linked.pk, plain.pk]}, format="json")

        assert response.status_code == status.HTTP_200_OK, response.content
        assert response.json() == {
            "purged": [plain.pk],
            "failed": [
                {"id": linked.pk, "name": "linked.txt", "message": str(CrossOrgCascadeError.default_detail)}
            ],
        }
        assert StorageFile.deleted_objects.filter(pk=linked.pk).exists()
        assert not StorageFile.all_objects.filter(pk=plain.pk).exists()
        assert GraphStorageFile.objects.filter(pk=link.pk).exists()
        assert _trash_keys(backend, acme) != set()

    def test_a_single_purge_raises_and_deletes_nothing(self, manager, backend, acme, beta, error_log):
        linked = _binned(manager, acme, "linked.txt")
        link = _linked_to_a_flow_of(beta, linked)
        trash_before = _trash_keys(backend, acme)

        with pytest.raises(CrossOrgCascadeError):
            StorageRecycleBinService(manager).purge(acme.id, linked.pk, actor="test")

        assert StorageFile.deleted_objects.filter(pk=linked.pk).exists()
        assert GraphStorageFile.objects.filter(pk=link.pk).exists()
        assert _trash_keys(backend, acme) == trash_before
        assert error_log == [_refusal_line(f"storage entry {linked.pk}", acme, link, beta)]

    def test_a_purge_of_a_file_linked_to_an_own_flow_takes_the_link_with_it(self, manager, acme):
        row = _binned(manager, acme, "own.txt")
        link = _linked_to_a_flow_of(acme, row)

        StorageRecycleBinService(manager).purge(acme.id, row.pk, actor="test")

        assert not StorageFile.all_objects.filter(pk=row.pk).exists()
        assert not GraphStorageFile.all_objects.filter(pk=link.pk).exists()

    def test_the_retention_job_keeps_the_linked_batch_logs_it_once_and_purges_the_rest(
        self, manager, acme, beta, settings, error_log
    ):
        settings.RECYCLE_BIN_RETENTION_DAYS = 7
        linked = _binned_days_ago(manager, acme, "linked.txt", 1, days_ago=8)
        plain = _binned_days_ago(manager, acme, "plain.txt", 1, days_ago=8)
        link = _linked_to_a_flow_of(beta, linked)

        with patch(
            "tables.services.recycle_bin.purge_service.get_storage_manager", return_value=manager
        ):
            result = PurgeService.purge_expired()

        assert result[StorageFile._meta.label] == 1
        assert StorageFile.deleted_objects.filter(pk=linked.pk).exists()
        assert not StorageFile.all_objects.filter(pk=plain.pk).exists()
        assert GraphStorageFile.objects.filter(pk=link.pk).exists()
        # One line, no traceback.
        assert error_log == [
            _refusal_line(f"storage batch {linked.soft_delete_batch}", acme, link, beta)
        ]

    def test_making_room_keeps_the_linked_entry_and_takes_the_next_oldest(
        self, manager, acme, beta, error_log
    ):
        linked = _binned_days_ago(manager, acme, "linked.txt", 10, days_ago=3)
        _binned_days_ago(manager, acme, "middle.txt", 10, days_ago=2)
        _binned_days_ago(manager, acme, "newest.txt", 10, days_ago=1)
        link = _linked_to_a_flow_of(beta, linked)

        with transaction.atomic():
            purged = StorageRecycleBinService(manager).make_room(acme.id, 15, actor="user 7")

        assert purged == [PurgedBinEntry("middle.txt", 10), PurgedBinEntry("newest.txt", 10)]
        assert set(StorageFile.deleted_objects.filter(org=acme).values_list("path", flat=True)) == {
            "linked.txt"
        }
        assert GraphStorageFile.objects.filter(pk=link.pk).exists()
        assert error_log == [_refusal_line(f"storage entry {linked.pk}", acme, link, beta)]

    def test_making_room_is_413_when_the_rest_of_the_bin_is_not_enough(self, manager, acme, beta):
        linked = _binned_days_ago(manager, acme, "linked.txt", 10, days_ago=3)
        _binned_days_ago(manager, acme, "other.txt", 10, days_ago=2)
        _linked_to_a_flow_of(beta, linked)

        with pytest.raises(StorageQuotaExceeded):
            with transaction.atomic():
                StorageRecycleBinService(manager).make_room(acme.id, 15, actor="user 7")

        assert set(StorageFile.deleted_objects.filter(org=acme).values_list("path", flat=True)) == {
            "linked.txt",
            "other.txt",
        }

    def test_making_room_logs_a_refusal_no_single_entry_explains_before_the_409(
        self, manager, acme, beta, error_log
    ):
        linked = _binned_days_ago(manager, acme, "linked.txt", 10, days_ago=3)
        other = _binned_days_ago(manager, acme, "other.txt", 10, days_ago=2)
        _linked_to_a_flow_of(beta, linked)

        # The entries are refused together, yet none is refused on its own.
        with patch.object(StorageRecycleBinService, "_refused_entries", return_value=set()):
            with pytest.raises(CrossOrgCascadeError):
                with transaction.atomic():
                    StorageRecycleBinService(manager).make_room(acme.id, 15, actor="user 7")

        assert error_log == [
            f"Refused to delete StorageFile {sorted([linked.pk, other.pk])} of org {acme.id} to make "
            "room: the entries together reach another organization's row, though none does on its own\n"
        ]
        assert StorageFile.deleted_objects.filter(org=acme).count() == 2
