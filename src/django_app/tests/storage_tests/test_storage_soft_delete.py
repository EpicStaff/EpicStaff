"""Deleting a storage file or folder bins its rows as one batch and moves its
objects under the reserved .recycle-bin/<batch>/ prefix."""

from unittest.mock import patch

import pytest

from agents.models import Surface, SurfaceStorageItem
from tables.models import Graph, GraphStorageFile, Session, SessionStorageFile, StorageFile
from tables.services.storage_service.base import SourceCleanupError
from tables.services.storage_service.db_sync import StorageFileSync, storage_file_link_models
from tables.services.storage_service.manager import StorageManager
from tables.services.storage_service.quota import org_used_bytes
from tests.storage_tests.in_memory_backend import InMemoryStorageBackend, seed_file

pytestmark = pytest.mark.django_db


@pytest.fixture
def manager():
    return StorageManager(InMemoryStorageBackend(organization_prefix=""))


def _objects(manager) -> dict:
    return manager._backend._objects


class TestSoftDelete:
    def test_a_file_moves_to_its_trash_batch(self, manager, org):
        seed_file(manager._backend, org.id, "docs/a.txt", b"old")

        batch = manager.delete(org.id, "docs/a.txt")

        assert f"org_{org.id}/docs/a.txt" not in _objects(manager)
        assert f"org_{org.id}/.recycle-bin/{batch}/docs/a.txt" in _objects(manager)
        row = StorageFile.all_objects.get(org=org, path="docs/a.txt")
        assert row.active is False
        assert row.soft_delete_batch == batch

    def test_a_new_upload_to_the_same_path_keeps_the_binned_bytes(self, manager, org):
        seed_file(manager._backend, org.id, "docs/a.txt", b"old")
        batch = manager.delete(org.id, "docs/a.txt")

        seed_file(manager._backend, org.id, "docs/a.txt", b"new")

        assert StorageFile.objects.filter(org=org, path="docs/a.txt").count() == 1
        assert _objects(manager)[f"org_{org.id}/.recycle-bin/{batch}/docs/a.txt"][0] == b"old"

    @pytest.mark.parametrize("path", ["docs", "docs/"])
    def test_a_folder_moves_with_everything_under_it_as_one_batch(self, manager, org, path):
        manager.mkdir(org.id, "docs")
        seed_file(manager._backend, org.id, "docs/a.txt", b"a")
        seed_file(manager._backend, org.id, "docs/sub/b.txt", b"b")

        batch = manager.delete(org.id, path)

        rows = StorageFile.all_objects.filter(org=org, path__startswith="docs/")
        assert {row.path for row in rows} == {"docs/", "docs/a.txt", "docs/sub/", "docs/sub/b.txt"}
        assert {row.soft_delete_batch for row in rows} == {batch}
        assert not any(row.active for row in rows)
        trash = f"org_{org.id}/.recycle-bin/{batch}/docs/"
        assert {key for key in _objects(manager) if key.startswith(trash)} >= {
            f"{trash}a.txt",
            f"{trash}sub/b.txt",
        }
        assert not any(key.startswith(f"org_{org.id}/docs/") for key in _objects(manager))

    def test_a_folder_with_no_marker_is_still_binned(self, manager, org):
        # An upload's ancestors get rows but no marker object.
        seed_file(manager._backend, org.id, "docs/a.txt", b"a")
        manager.delete(org.id, "docs/a.txt")

        assert manager.delete(org.id, "docs") is not None

        assert StorageFile.deleted_objects.filter(org=org, path="docs/").exists()

    def test_nothing_live_at_the_path_is_a_no_op(self, manager, org):
        manager._backend.put_bytes(f"org_{org.id}/unindexed.txt", b"x")

        assert manager.delete(org.id, "unindexed.txt") is None

        assert f"org_{org.id}/unindexed.txt" in _objects(manager)

    def test_binned_files_disappear_from_live_reads(self, manager, org):
        seed_file(manager._backend, org.id, "a.txt", b"a")
        manager.delete(org.id, "a.txt")

        assert manager.list_(org.id, "") == []
        with pytest.raises(FileNotFoundError):
            manager.download(org.id, "a.txt")
        assert manager.search(org.id, "a")[1] == 0

    @pytest.mark.parametrize("path", [".recycle-bin", ".recycle-bin/x.txt", "/.recycle-bin/b/x.txt"])
    def test_the_trash_folder_is_reserved(self, manager, org, path):
        with pytest.raises(ValueError):
            manager.mkdir(org.id, path)
        with pytest.raises(ValueError):
            manager.exists(org.id, path)


class TestOnSoftDelete:
    def test_links_to_a_binned_file_are_removed(self, org):
        StorageFileSync.on_upload(org.id, "a.txt", size=1)
        row = StorageFile.objects.get(org=org, path="a.txt")
        graph = Graph.objects.create(org=org, name="Uses a file")
        GraphStorageFile.objects.create(graph=graph, storage_file=row)
        SessionStorageFile.objects.create(session=Session.objects.create(graph=graph), storage_file=row)
        surface = Surface.objects.create(organization=org, name="Reads a file")
        SurfaceStorageItem.objects.create(surface=surface, storage_file=row)

        StorageFileSync.on_soft_delete(org.id, "a.txt")

        assert not GraphStorageFile.all_objects.filter(storage_file=row).exists()
        assert not SessionStorageFile.objects.filter(storage_file=row).exists()
        assert not SurfaceStorageItem.all_objects.filter(storage_file=row).exists()

    def test_a_sibling_outside_the_folder_stays_live(self, org):
        StorageFileSync.on_upload(org.id, "docs/a/x.txt", size=1)
        StorageFileSync.on_upload(org.id, "docs/b.txt", size=1)

        StorageFileSync.on_soft_delete(org.id, "docs/a/")

        assert StorageFile.objects.filter(org=org, path="docs/b.txt").exists()
        assert not StorageFile.objects.filter(org=org, path="docs/a/x.txt").exists()

    def test_trash_paths_are_never_indexed(self, org):
        StorageFileSync.on_upload(org.id, ".recycle-bin/b/x.txt", size=1)

        assert not StorageFile.all_objects.filter(org=org, path__startswith=".recycle-bin").exists()


class TestDeleteFailures:
    def test_a_failed_move_leaves_everything_live_and_no_trash(self, manager, org, monkeypatch):
        seed_file(manager._backend, org.id, "docs/a.txt", b"a")
        seed_file(manager._backend, org.id, "docs/b.txt", b"b")
        row = StorageFile.objects.get(org=org, path="docs/a.txt")
        graph = Graph.objects.create(org=org, name="Uses a file")
        GraphStorageFile.objects.create(graph=graph, storage_file=row)
        real_rename = manager._backend.rename

        def rename_then_fail(source, destination):
            real_rename(source, destination)  # the copies land in the trash...
            manager._backend.put_bytes(source + "/a.txt", b"a")  # ...the sources stay...
            manager._backend.put_bytes(source + "/b.txt", b"b")
            raise RuntimeError("delete_objects failed")  # ...and deleting them fails

        monkeypatch.setattr(manager._backend, "rename", rename_then_fail)

        with pytest.raises(RuntimeError):
            manager.delete(org.id, "docs")

        assert StorageFile.objects.filter(org=org, path__startswith="docs/").count() == 3
        assert GraphStorageFile.objects.filter(storage_file=row).exists()
        assert not any(".recycle-bin" in key for key in _objects(manager))
        assert _objects(manager)[f"org_{org.id}/docs/a.txt"][0] == b"a"

    def _rename_then_fail_deleting_sources(self, manager, monkeypatch):
        """Copy everything to the trash, delete only some sources, then fail (a DeleteObjects batch error)."""
        real_rename = manager._backend.rename

        def rename(source, destination):
            source_keys = [key for key in _objects(manager) if key.startswith(source + "/")]
            real_rename(source, destination)
            manager._backend.put_bytes(source + "/b.txt", b"b")  # its delete failed
            raise SourceCleanupError(source_keys)

        monkeypatch.setattr(manager._backend, "rename", rename)

    def test_a_failed_source_delete_keeps_the_trash_and_bins_the_rows(self, manager, org, monkeypatch):
        seed_file(manager._backend, org.id, "docs/a.txt", b"a")
        seed_file(manager._backend, org.id, "docs/b.txt", b"b")
        self._rename_then_fail_deleting_sources(manager, monkeypatch)

        batch = manager.delete(org.id, "docs")

        trash = f"org_{org.id}/.recycle-bin/{batch}/docs/"
        assert _objects(manager)[f"{trash}a.txt"][0] == b"a"
        assert _objects(manager)[f"{trash}b.txt"][0] == b"b"
        assert not any(key.startswith(f"org_{org.id}/docs/") for key in _objects(manager))
        assert not StorageFile.objects.filter(org=org, path__startswith="docs/").exists()

    def test_leftover_sources_that_cannot_be_deleted_stay_and_nothing_is_lost(
        self, manager, org, monkeypatch
    ):
        seed_file(manager._backend, org.id, "docs/a.txt", b"a")
        seed_file(manager._backend, org.id, "docs/b.txt", b"b")
        self._rename_then_fail_deleting_sources(manager, monkeypatch)
        monkeypatch.setattr(manager._backend, "delete_keys", lambda keys: (_ for _ in ()).throw(RuntimeError("down")))

        batch = manager.delete(org.id, "docs")

        trash = f"org_{org.id}/.recycle-bin/{batch}/docs/"
        assert {f"{trash}a.txt", f"{trash}b.txt"} <= set(_objects(manager))
        assert StorageFile.deleted_objects.filter(org=org, path="docs/a.txt").exists()

    def test_deleting_the_same_path_twice_is_a_no_op_the_second_time(self, manager, org):
        seed_file(manager._backend, org.id, "a.txt", b"a")
        manager.delete(org.id, "a.txt")

        assert manager.delete(org.id, "a.txt") is None

    def test_a_delete_does_not_free_quota(self, manager, org):
        seed_file(manager._backend, org.id, "a.txt", b"abcde")

        manager.delete(org.id, "a.txt")

        assert org_used_bytes(org.id) == 5


def test_every_storage_file_link_is_listed():
    # _delete_links_to hard-deletes these; a new FK onto StorageFile must be added
    # there on purpose (it might need PROTECT or SET_NULL handling instead).
    linking_models = {
        field.related_model
        for field in StorageFile._meta.get_fields(include_hidden=True)
        if field.one_to_many and field.auto_created and not field.concrete
    }

    assert linking_models == set(storage_file_link_models())


class TestDeleteEndpoint:
    URL = "/api/storage/delete/"

    @pytest.fixture
    def real_manager(self):
        storage_manager = StorageManager(InMemoryStorageBackend(organization_prefix=""))
        with patch("tables.views.storage_views.get_storage_manager", return_value=storage_manager):
            yield storage_manager

    def test_deletes_into_the_bin(self, auth_client, default_org, real_manager):
        seed_file(real_manager._backend, default_org.id, "a.txt", b"a")

        response = auth_client.delete(self.URL, {"paths": ["a.txt"]}, format="json")

        assert response.status_code == 204, response.content
        assert StorageFile.deleted_objects.filter(org=default_org, path="a.txt").exists()

    @pytest.mark.parametrize("bad_path", [".recycle-bin/x.txt", "", "/"])
    def test_a_bad_path_is_400_and_nothing_is_deleted(self, auth_client, default_org, real_manager, bad_path):
        seed_file(real_manager._backend, default_org.id, "a.txt", b"a")

        response = auth_client.delete(self.URL, {"paths": ["a.txt", bad_path]}, format="json")

        assert response.status_code == 400, response.content
        assert StorageFile.objects.filter(org=default_org, path="a.txt").exists()


def test_a_rename_whose_source_cleanup_fails_still_records_the_move(manager, org, monkeypatch):
    seed_file(manager._backend, org.id, "old.txt", b"a")
    real_rename = manager._backend.rename

    def rename_then_fail_cleanup(source, destination):
        real_rename(source, destination)
        manager._backend.put_bytes(source, b"a")  # its delete failed
        raise SourceCleanupError([source])

    monkeypatch.setattr(manager._backend, "rename", rename_then_fail_cleanup)

    manager.rename(org.id, "old.txt", "new.txt")

    assert StorageFile.objects.filter(org=org, path="new.txt").exists()
    assert not StorageFile.objects.filter(org=org, path="old.txt").exists()
    assert f"org_{org.id}/old.txt" not in _objects(manager)
