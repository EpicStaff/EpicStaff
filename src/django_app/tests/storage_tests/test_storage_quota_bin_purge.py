"""A write that doesn't fit the org's storage quota purges the org's oldest storage
recycle bin entries first, just enough of them, and reports them -- but only for a
caller the view grants it to: a user session holding FILES:DELETE in the org.

Real InMemoryStorageBackend, real StorageManager, recycle bin service, quota module, DB.
"""

import io
from datetime import timedelta

import pytest
from django.db import transaction
from django.utils import timezone
from loguru import logger
from rest_framework.test import APIClient

from rbac.models import OrganizationUser, Role, RolePermission
from rbac.models.enums import Permission, ResourceType
from tables.exceptions import StorageQuotaExceeded
from tables.models import StorageFile
from tables.services.storage_service.dataclasses import BinPurgeGrant, PurgedBinEntry
from tables.services.storage_service.db_sync import StorageFileSync
from tables.services.storage_service.manager import StorageManager
from tables.services.storage_service.path_utils import storage_key, trash_batch_prefix
from tables.services.storage_service.quota import (
    ensure_fits_quota,
    org_used_bytes,
    record_files_within_quota,
)
from tables.services.storage_service.recycle_bin import StorageRecycleBinService
from tables.services.storage_service.upload import archive_upload
from tables.services.storage_service.upload.file_upload import _undo_file_row, _write_file_row
from tables.validators.file_upload_validator import FileValidator
from tables.views import storage_views
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403
from tests.storage_tests.in_memory_backend import InMemoryStorageBackend, seed_file, zip_bytes

pytestmark = pytest.mark.django_db

GRANT = BinPurgeGrant(actor="user 7")


@pytest.fixture
def backend():
    return InMemoryStorageBackend(organization_prefix="")


@pytest.fixture
def manager(backend):
    return StorageManager(backend)


@pytest.fixture
def recycle_bin(manager):
    return StorageRecycleBinService(manager)


@pytest.fixture
def quota(settings):
    """Set the org quota after the test has seeded its files under the default one."""

    def set_quota(size: int) -> None:
        settings.ORG_STORAGE_QUOTA = size

    return set_quota


@pytest.fixture
def log_lines():
    """Every loguru line logged during the test, at INFO and above."""
    lines: list[str] = []
    sink_id = logger.add(lambda message: lines.append(str(message)), level="INFO")
    yield lines
    logger.remove(sink_id)


def _bin_file(manager, org, path: str, size: int, days_ago: int):
    """Store a file, delete it into the bin and date its deletion `days_ago` days back."""
    seed_file(manager._backend, org.id, path, b"x" * size)
    return _delete(manager, org, path, days_ago)


def _delete(manager, org, path: str, days_ago: int):
    batch = manager.delete(org.id, path, user=None)
    StorageFile.deleted_objects.filter(org=org, soft_delete_batch=batch).update(
        soft_deleted_at=timezone.now() - timedelta(days=days_ago)
    )
    return batch


def _binned_paths(org) -> set[str]:
    return set(StorageFile.deleted_objects.filter(org=org).values_list("path", flat=True))


def _live_paths(org) -> set[str]:
    return set(StorageFile.objects.filter(org=org).values_list("path", flat=True))


def _trash_keys(backend, org, batch) -> list[str]:
    prefix = trash_batch_prefix(org.id, batch)
    return [key for key in backend._objects if key.startswith(prefix)]


def _record(org, recycle_bin, path: str, size: int, bin_purge: BinPurgeGrant | None = GRANT):
    return record_files_within_quota(
        org.id, [(path, size)], recycle_bin=recycle_bin, bin_purge=bin_purge
    )


class TestMakeRoom:
    def test_a_write_that_fits_purges_nothing(self, manager, recycle_bin, org, quota):
        _bin_file(manager, org, "old.txt", 10, days_ago=3)
        quota(30)

        assert _record(org, recycle_bin, "new.txt", 20) == []

        assert _binned_paths(org) == {"old.txt"}
        assert _live_paths(org) == {"new.txt"}

    def test_the_oldest_entries_go_first_and_only_as_many_as_needed(
        self, manager, backend, recycle_bin, org, quota, django_capture_on_commit_callbacks
    ):
        oldest = _bin_file(manager, org, "oldest.txt", 10, days_ago=3)
        middle = _bin_file(manager, org, "middle.txt", 10, days_ago=2)
        newest = _bin_file(manager, org, "newest.txt", 10, days_ago=1)
        quota(40)

        # 30 binned + 25 new is 15 over: the oldest alone frees 10, so two go.
        with django_capture_on_commit_callbacks(execute=True):
            purged = _record(org, recycle_bin, "upload.bin", 25)

        assert purged == [PurgedBinEntry("oldest.txt", 10), PurgedBinEntry("middle.txt", 10)]
        assert _binned_paths(org) == {"newest.txt"}
        assert _live_paths(org) == {"upload.bin"}
        assert org_used_bytes(org.id) == 35
        assert _trash_keys(backend, org, oldest) == []
        assert _trash_keys(backend, org, middle) == []
        assert _trash_keys(backend, org, newest) != []

    def test_a_binned_folder_goes_whole_with_what_was_deleted_with_it(
        self, manager, backend, recycle_bin, org, quota, django_capture_on_commit_callbacks
    ):
        seed_file(backend, org.id, "docs/a.txt", b"x" * 4)
        seed_file(backend, org.id, "docs/sub/b.txt", b"x" * 6)
        folder_batch = _delete(manager, org, "docs", days_ago=3)
        _bin_file(manager, org, "later.txt", 10, days_ago=1)
        quota(30)

        with django_capture_on_commit_callbacks(execute=True):
            purged = _record(org, recycle_bin, "upload.bin", 15)

        assert purged == [PurgedBinEntry("docs/", 10)]
        assert _binned_paths(org) == {"later.txt"}
        assert not StorageFile.all_objects.filter(org=org, soft_delete_batch=folder_batch).exists()
        assert _trash_keys(backend, org, folder_batch) == []

    def test_when_the_whole_bin_is_not_enough_nothing_is_purged(
        self, manager, backend, recycle_bin, org, quota, django_capture_on_commit_callbacks
    ):
        first = _bin_file(manager, org, "a.txt", 10, days_ago=3)
        second = _bin_file(manager, org, "b.txt", 10, days_ago=2)
        objects_before = dict(backend._objects)
        quota(30)

        with django_capture_on_commit_callbacks(execute=True) as callbacks:
            with pytest.raises(StorageQuotaExceeded):
                _record(org, recycle_bin, "upload.bin", 31)

        assert callbacks == []
        assert _binned_paths(org) == {"a.txt", "b.txt"}
        assert "upload.bin" not in _live_paths(org)
        assert backend._objects == objects_before
        assert _trash_keys(backend, org, first) and _trash_keys(backend, org, second)

    def test_without_a_grant_the_bin_counts_as_used_and_nothing_is_purged(
        self, manager, backend, recycle_bin, org, quota, django_capture_on_commit_callbacks
    ):
        batch = _bin_file(manager, org, "old.txt", 10, days_ago=3)
        quota(25)

        # 10 binned + 20 new is 5 over: purging old.txt would fit it, but there is no grant.
        with pytest.raises(StorageQuotaExceeded):
            ensure_fits_quota(org.id, 20, bin_purge=None)
        ensure_fits_quota(org.id, 20, bin_purge=GRANT)
        with django_capture_on_commit_callbacks(execute=True) as callbacks:
            with pytest.raises(StorageQuotaExceeded):
                _record(org, recycle_bin, "upload.bin", 20, bin_purge=None)

        assert callbacks == []
        assert _binned_paths(org) == {"old.txt"}
        assert _trash_keys(backend, org, batch) != []
        # A write that fits needs no grant.
        assert _record(org, recycle_bin, "small.bin", 15, bin_purge=None) == []

    def test_live_files_are_never_purged(self, manager, backend, recycle_bin, org, quota):
        seed_file(backend, org.id, "live.txt", b"x" * 20)
        _bin_file(manager, org, "binned.txt", 5, days_ago=3)
        quota(30)

        # 6 over, the bin holds 5: only purging the live file would make room.
        with pytest.raises(StorageQuotaExceeded):
            _record(org, recycle_bin, "upload.bin", 11)
        assert _binned_paths(org) == {"binned.txt"}

        purged = _record(org, recycle_bin, "upload.bin", 10)

        assert [entry.name for entry in purged] == ["binned.txt"]
        assert _live_paths(org) == {"live.txt", "upload.bin"}
        assert backend._objects[storage_key(org.id, "live.txt")][0] == b"x" * 20

    def test_another_orgs_bin_is_never_touched(
        self, manager, backend, recycle_bin, org, second_org, quota
    ):
        # The other org's entry is older and bigger, so it would be picked first.
        other_batch = _bin_file(manager, second_org, "theirs.bin", 50, days_ago=30)
        _bin_file(manager, org, "ours.txt", 5, days_ago=1)
        quota(30)

        with pytest.raises(StorageQuotaExceeded):
            _record(org, recycle_bin, "upload.bin", 40)
        purged = _record(org, recycle_bin, "upload.bin", 28)

        assert [entry.name for entry in purged] == ["ours.txt"]
        assert _binned_paths(second_org) == {"theirs.bin"}
        assert _trash_keys(backend, second_org, other_batch) != []

    def test_entries_that_free_no_bytes_are_kept(self, manager, recycle_bin, org, quota):
        manager.mkdir(org.id, "empty")
        _delete(manager, org, "empty", days_ago=5)
        _bin_file(manager, org, "old.txt", 10, days_ago=3)
        quota(10)

        purged = _record(org, recycle_bin, "upload.bin", 10)

        assert [entry.name for entry in purged] == ["old.txt"]
        assert _binned_paths(org) == {"empty/"}

    def test_trash_objects_go_only_once_the_write_commits(
        self, manager, backend, recycle_bin, org, quota, django_capture_on_commit_callbacks
    ):
        batch = _bin_file(manager, org, "old.txt", 10, days_ago=3)
        quota(10)

        with django_capture_on_commit_callbacks() as callbacks:
            _record(org, recycle_bin, "upload.bin", 10)

            assert not StorageFile.all_objects.filter(org=org, path="old.txt").exists()
            assert _trash_keys(backend, org, batch) != []

        for callback in callbacks:
            callback()
        assert _trash_keys(backend, org, batch) == []

    def test_a_write_failing_after_the_purge_keeps_the_bin_whole(
        self, manager, backend, recycle_bin, org, quota, monkeypatch, django_capture_on_commit_callbacks
    ):
        batch = _bin_file(manager, org, "old.txt", 10, days_ago=3)
        quota(10)

        def _failing_row_write(*_args, **_kwargs):
            raise RuntimeError("database hiccup")

        monkeypatch.setattr(StorageFileSync, "on_bulk_upload", staticmethod(_failing_row_write))
        with django_capture_on_commit_callbacks(execute=True) as callbacks:
            with pytest.raises(RuntimeError):
                _record(org, recycle_bin, "upload.bin", 10)

        assert callbacks == []
        assert _binned_paths(org) == {"old.txt"}
        assert _trash_keys(backend, org, batch) != []

    def test_each_purged_entry_is_logged_with_its_org_size_actor_and_reason(
        self, manager, recycle_bin, org, quota, django_capture_on_commit_callbacks, log_lines
    ):
        _bin_file(manager, org, "old.txt", 10, days_ago=3)
        _bin_file(manager, org, "older.txt", 7, days_ago=4)
        quota(17)

        with django_capture_on_commit_callbacks(execute=True):
            _record(org, recycle_bin, "upload.bin", 17, bin_purge=BinPurgeGrant("user 7 via API key 3"))

        purge_lines = [line for line in log_lines if "reason: storage quota" in line]
        assert len(purge_lines) == 2
        assert f"older.txt (7 bytes) of org {org.id} by user 7 via API key 3" in purge_lines[0]
        assert f"old.txt (10 bytes) of org {org.id} by user 7 via API key 3" in purge_lines[1]

    def test_a_failing_trash_delete_is_logged_and_the_write_stands(
        self, manager, backend, recycle_bin, org, quota, monkeypatch, django_capture_on_commit_callbacks, log_lines
    ):
        _bin_file(manager, org, "old.txt", 10, days_ago=3)
        quota(10)

        def _unreachable(*_args, **_kwargs):
            raise RuntimeError("storage down")

        monkeypatch.setattr(backend, "delete_prefix", _unreachable)
        with django_capture_on_commit_callbacks(execute=True):
            purged = _record(org, recycle_bin, "upload.bin", 10)

        assert [entry.name for entry in purged] == ["old.txt"]
        assert _live_paths(org) == {"upload.bin"}
        assert any("left behind after a storage quota purge" in line for line in log_lines)


class TestConcurrentPurges:
    """The branches a concurrent purge or an unlocked agent write lead to, made deterministic."""

    def test_make_room_skips_an_entry_purged_by_someone_else_after_the_pick(
        self, manager, recycle_bin, org, monkeypatch
    ):
        _bin_file(manager, org, "first.txt", 10, days_ago=3)
        _bin_file(manager, org, "second.txt", 10, days_ago=2)
        pick = StorageRecycleBinService._oldest_entries_freeing

        def _pick_then_lose_the_first(org_id, needed_bytes):
            chosen = pick(org_id, needed_bytes)
            # A user or retention purge takes first.txt between the pick and the lock.
            StorageFile.all_objects.filter(org_id=org_id, path="first.txt").delete()
            return chosen

        monkeypatch.setattr(
            StorageRecycleBinService,
            "_oldest_entries_freeing",
            staticmethod(_pick_then_lose_the_first),
        )

        with transaction.atomic():
            purged = recycle_bin.make_room(org.id, 20, actor="user 7")

        assert purged == [PurgedBinEntry("second.txt", 10)]
        assert _binned_paths(org) == set()

    def test_the_locked_recheck_refuses_a_write_make_room_fell_short_for(
        self, manager, backend, recycle_bin, org, quota, monkeypatch, django_capture_on_commit_callbacks
    ):
        first = _bin_file(manager, org, "first.txt", 10, days_ago=3)
        second = _bin_file(manager, org, "second.txt", 10, days_ago=2)
        quota(30)
        pick = StorageRecycleBinService._oldest_entries_freeing

        def _pick_too_few(org_id, needed_bytes):
            # Stands in for an agent write landing after the shortfall was measured: what
            # the pick frees no longer covers this write.
            return pick(org_id, needed_bytes)[:1]

        monkeypatch.setattr(
            StorageRecycleBinService, "_oldest_entries_freeing", staticmethod(_pick_too_few)
        )

        # 20 binned + 25 new is 15 over: first.txt alone frees only 10.
        with django_capture_on_commit_callbacks(execute=True) as callbacks:
            with pytest.raises(StorageQuotaExceeded):
                _record(org, recycle_bin, "upload.bin", 25)

        assert callbacks == []
        assert _binned_paths(org) == {"first.txt", "second.txt"}
        assert "upload.bin" not in _live_paths(org)
        assert _trash_keys(backend, org, first) and _trash_keys(backend, org, second)


class TestServiceWrites:
    def test_copy_purges_the_oldest_entries_and_returns_them(self, manager, org, quota):
        seed_file(manager._backend, org.id, "a.txt", b"x" * 10)
        _bin_file(manager, org, "old.txt", 10, days_ago=3)
        _bin_file(manager, org, "new.txt", 10, days_ago=1)
        quota(35)

        purged = manager.copy(org.id, "a.txt", "", bin_purge=GRANT)

        assert purged == [PurgedBinEntry("old.txt", 10)]
        assert _live_paths(org) == {"a.txt", "a (1).txt"}
        assert _binned_paths(org) == {"new.txt"}

    def test_copy_without_a_grant_is_a_413_and_purges_nothing(self, manager, backend, org, quota):
        seed_file(backend, org.id, "a.txt", b"x" * 10)
        _bin_file(manager, org, "old.txt", 10, days_ago=3)
        quota(25)

        with pytest.raises(StorageQuotaExceeded):
            manager.copy(org.id, "a.txt", "")

        assert _live_paths(org) == {"a.txt"}
        assert _binned_paths(org) == {"old.txt"}

    @pytest.mark.parametrize("operation", ["copy_cross_org", "move_cross_org"])
    def test_cross_org_writes_purge_only_the_destination_bin(
        self, manager, org, second_org, quota, operation
    ):
        seed_file(manager._backend, org.id, "a.txt", b"x" * 10)
        _bin_file(manager, org, "source-old.txt", 10, days_ago=9)
        _bin_file(manager, second_org, "old.txt", 10, days_ago=3)
        quota(15)

        purged = getattr(manager, operation)(org.id, "a.txt", second_org.id, "", bin_purge=GRANT)

        assert [entry.name for entry in purged] == ["old.txt"]
        assert _binned_paths(second_org) == set()
        assert _binned_paths(org) == {"source-old.txt"}
        assert "a.txt" in _live_paths(second_org)

    @pytest.mark.parametrize("operation", ["copy_cross_org", "move_cross_org"])
    def test_cross_org_writes_without_a_grant_are_a_413_and_purge_nothing(
        self, manager, org, second_org, quota, operation
    ):
        seed_file(manager._backend, org.id, "a.txt", b"x" * 10)
        _bin_file(manager, second_org, "old.txt", 10, days_ago=3)
        quota(15)

        with pytest.raises(StorageQuotaExceeded):
            getattr(manager, operation)(org.id, "a.txt", second_org.id, "")

        assert _binned_paths(second_org) == {"old.txt"}
        assert _live_paths(org) == {"a.txt"}

    @pytest.mark.parametrize(("bin_purge", "purges"), [(GRANT, True), (None, False)])
    def test_a_plain_upload_row_purges_only_under_a_grant(
        self, manager, recycle_bin, org, quota, bin_purge, purges
    ):
        _bin_file(manager, org, "old.txt", 10, days_ago=3)
        quota(25)

        if purges:
            _, purged = _write_file_row(org.id, "note.txt", 20, None, None, recycle_bin, bin_purge)
            assert purged == [PurgedBinEntry("old.txt", 10)]
            assert _binned_paths(org) == set()
        else:
            with pytest.raises(StorageQuotaExceeded):
                _write_file_row(org.id, "note.txt", 20, None, None, recycle_bin, bin_purge)
            assert _binned_paths(org) == {"old.txt"}

    @pytest.mark.parametrize(("bin_purge", "purges"), [(GRANT, True), (None, False)])
    def test_an_archive_unpack_purges_only_under_a_grant(
        self, manager, backend, org, quota, bin_purge, purges
    ):
        _bin_file(manager, org, "old.txt", 10, days_ago=3)
        quota(15)
        buffered = io.BytesIO(zip_bytes({"a.txt": b"hello", "b.txt": b"world"}))

        def unpack():
            return archive_upload._unpack_to_storage(
                org.id, "", "bundle.zip", buffered, backend, FileValidator(), None, bin_purge
            )

        if purges:
            result = unpack()
            assert result["extracted"] == ["bundle/a.txt", "bundle/b.txt"]
            assert result["recycle_bin_purged"] == [PurgedBinEntry("old.txt", 10)]
            assert _binned_paths(org) == set()
        else:
            with pytest.raises(StorageQuotaExceeded):
                unpack()
            assert _binned_paths(org) == {"old.txt"}


class TestUploadFailingAfterThePurge:
    def test_the_undo_warns_with_the_purged_entries_and_the_actor(
        self, manager, backend, recycle_bin, org, quota, log_lines
    ):
        _bin_file(manager, org, "old.txt", 10, days_ago=3)
        quota(25)
        replaced, purged = _write_file_row(org.id, "note.txt", 20, None, None, recycle_bin, GRANT)

        # The store never completed the upload: no object at the target.
        _undo_file_row(org.id, "note.txt", 20, replaced, backend, purged, GRANT)

        assert "note.txt" not in _live_paths(org)
        assert _binned_paths(org) == set()
        warnings = [line for line in log_lines if "stay purged" in line]
        assert len(warnings) == 1
        assert "WARNING" in warnings[0]
        assert "old.txt (10 bytes)" in warnings[0]
        assert "by user 7" in warnings[0]
        assert f"org {org.id}" in warnings[0]

    def test_an_undo_with_nothing_purged_does_not_warn(self, backend, recycle_bin, org, log_lines):
        replaced, purged = _write_file_row(org.id, "note.txt", 20, None, None, recycle_bin, None)

        _undo_file_row(org.id, "note.txt", 20, replaced, backend, purged, None)

        assert "note.txt" not in _live_paths(org)
        assert not [line for line in log_lines if "stay purged" in line]

    def test_an_upload_the_store_did_complete_does_not_warn(
        self, manager, backend, recycle_bin, org, quota, log_lines
    ):
        _bin_file(manager, org, "old.txt", 10, days_ago=3)
        quota(25)
        replaced, purged = _write_file_row(org.id, "note.txt", 20, None, None, recycle_bin, GRANT)
        backend.put_bytes(storage_key(org.id, "note.txt"), b"y" * 20)

        _undo_file_row(org.id, "note.txt", 20, replaced, backend, purged, GRANT)

        assert "note.txt" in _live_paths(org)
        assert not [line for line in log_lines if "stay purged" in line]


# --- the API: who may cause a purge, and who sees the purged names -----------------


@pytest.fixture
def api_manager(monkeypatch):
    """The StorageManager every storage API call in the test goes to."""
    manager = StorageManager(InMemoryStorageBackend(organization_prefix=""))
    monkeypatch.setattr(storage_views, "get_storage_manager", lambda: manager)
    return manager


@pytest.fixture
def client_in_acme(client_as, acme):
    def _make(user) -> APIClient:
        client = client_as(user)
        client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
        return client

    return _make


@pytest.fixture
def user_with_files_bits(django_user_model, acme):
    """Factory: a member of Acme whose custom role grants exactly `bits` on FILES."""

    def _make(bits: Permission):
        role = Role.objects.create(name=f"Files {int(bits)}", org=acme, is_built_in=False)
        RolePermission.objects.create(
            role=role, resource_type=ResourceType.FILES.value, permissions=int(bits)
        )
        user = django_user_model.objects.create_user(
            email=f"files-{int(bits)}@example.com", password="StrongPass123!"
        )
        OrganizationUser.objects.create(user=user, org=acme, role=role)
        return user

    return _make


@pytest.fixture
def acme_one_binned_file_short(api_manager, acme, quota):
    """Acme holds a.txt (10 bytes) and old.txt (10 bytes, binned); a copy of a.txt fits
    only once old.txt is purged."""
    seed_file(api_manager._backend, acme.id, "a.txt", b"x" * 10)
    _bin_file(api_manager, acme, "old.txt", 10, days_ago=3)
    quota(25)


def _copy(client, **extra):
    return client.post(
        "/api/storage/copy/", {"from_path": "a.txt", "to_path": "/", **extra}, format="json"
    )


@pytest.mark.usefixtures("acme_one_binned_file_short")
class TestCopyApi:
    def test_a_member_with_files_delete_purges_and_sees_the_names(
        self, client_in_acme, admin_acme, acme
    ):
        response = _copy(client_in_acme(admin_acme))

        assert response.status_code == 200, response.content
        assert response.json() == {
            "from": "a.txt",
            "to": "",
            "success": True,
            "recycle_bin_purged": [{"name": "old.txt", "size": 10}],
        }
        assert _binned_paths(acme) == set()

    def test_a_member_without_files_delete_gets_a_413_and_the_bin_stays_whole(
        self, client_in_acme, member_only, acme
    ):
        response = _copy(client_in_acme(member_only))

        assert response.status_code == 413, response.content
        assert response.json()["code"] == "storage_quota_exceeded"
        assert _binned_paths(acme) == {"old.txt"}
        assert _live_paths(acme) == {"a.txt"}

    @pytest.mark.parametrize("key_owner", ["org_admin", "superadmin"])
    def test_an_api_key_gets_a_413_and_the_bin_stays_whole(
        self, issue_api_key, admin_acme, superadmin, acme, key_owner
    ):
        raw_key, _ = issue_api_key(user=admin_acme if key_owner == "org_admin" else superadmin)
        client = APIClient()
        client.credentials(HTTP_X_API_KEY=raw_key, HTTP_X_ORGANIZATION_ID=str(acme.id))

        response = _copy(client)

        assert response.status_code == 413, response.content
        assert _binned_paths(acme) == {"old.txt"}

    def test_a_caller_without_files_read_gets_the_sizes_but_no_names(
        self, client_in_acme, user_with_files_bits, acme
    ):
        writer = user_with_files_bits(Permission.UPDATE | Permission.DELETE)

        response = _copy(client_in_acme(writer))

        assert response.status_code == 200, response.content
        assert response.json()["recycle_bin_purged"] == [{"name": None, "size": 10}]
        assert _binned_paths(acme) == set()

    def test_the_purge_log_names_the_user_who_caused_it(
        self, client_in_acme, admin_acme, django_capture_on_commit_callbacks, log_lines
    ):
        with django_capture_on_commit_callbacks(execute=True):
            response = _copy(client_in_acme(admin_acme))

        assert response.status_code == 200, response.content
        purge_lines = [line for line in log_lines if "reason: storage quota" in line]
        assert len(purge_lines) == 1
        assert f"by user {admin_acme.pk}," in purge_lines[0]

    def test_a_copy_that_fits_reports_an_empty_list(self, client_in_acme, member_only, acme, quota):
        quota(10**6)

        response = _copy(client_in_acme(member_only))

        assert response.status_code == 200, response.content
        assert response.json()["recycle_bin_purged"] == []
        assert _binned_paths(acme) == {"old.txt"}

    def test_past_the_whole_bin_is_a_413_and_purges_nothing(
        self, client_in_acme, admin_acme, acme, quota
    ):
        # 30 used and 10 more is 21 over the quota; the bin frees only 10.
        quota(19)

        response = _copy(client_in_acme(admin_acme))

        assert response.status_code == 413
        assert response.json()["code"] == "storage_quota_exceeded"
        assert _binned_paths(acme) == {"old.txt"}


class TestCrossOrgApi:
    @pytest.fixture(autouse=True)
    def beta_full_but_for_its_bin(self, api_manager, acme, beta, quota):
        seed_file(api_manager._backend, acme.id, "a.txt", b"x" * 10)
        _bin_file(api_manager, beta, "old.txt", 10, days_ago=3)
        quota(15)

    @pytest.mark.parametrize("operation", ["copy", "move"])
    def test_a_superadmin_session_purges_the_destination_bin(
        self, superadmin_in_acme, acme, beta, operation
    ):
        response = superadmin_in_acme.post(
            f"/api/storage/{operation}/",
            {
                "from_path": "a.txt",
                "to_path": "/",
                "source_org_id": acme.id,
                "destination_org_id": beta.id,
            },
            format="json",
        )

        assert response.status_code == 200, response.content
        assert response.json()["recycle_bin_purged"] == [{"name": "old.txt", "size": 10}]
        assert _binned_paths(beta) == set()
        assert "a.txt" in _live_paths(beta)

    @pytest.mark.parametrize("operation", ["copy", "move"])
    def test_a_superadmin_api_key_gets_a_413_and_the_destination_bin_stays_whole(
        self, issue_api_key, superadmin, acme, beta, operation
    ):
        raw_key, _ = issue_api_key(user=superadmin)
        client = APIClient()
        client.credentials(HTTP_X_API_KEY=raw_key, HTTP_X_ORGANIZATION_ID=str(acme.id))

        response = client.post(
            f"/api/storage/{operation}/",
            {
                "from_path": "a.txt",
                "to_path": "/",
                "source_org_id": acme.id,
                "destination_org_id": beta.id,
            },
            format="json",
        )

        assert response.status_code == 413, response.content
        assert _binned_paths(beta) == {"old.txt"}
        assert _live_paths(acme) == {"a.txt"}


def test_a_move_within_one_org_reports_an_empty_list(client_in_acme, admin_acme, api_manager, acme):
    seed_file(api_manager._backend, acme.id, "a.txt", b"x" * 10)
    api_manager.mkdir(acme.id, "inbox")

    response = client_in_acme(admin_acme).post(
        "/api/storage/move/", {"from_path": "a.txt", "to_path": "inbox"}, format="json"
    )

    assert response.status_code == 200, response.content
    assert response.json()["recycle_bin_purged"] == []
