"""Recycle-bin storage rows are invisible to every live read and write path,
and the reconciler leaves them alone."""

import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.utils import timezone

from tables.models import StorageFile
from tables.services.storage_service.db_sync import StorageFileSync
from tables.services.storage_service.manager import StorageManager
from tables.services.storage_service.quota import org_used_bytes
from tables.services.storage_service.reconciler import StorageReconciler
from tests.storage_tests.in_memory_backend import InMemoryStorageBackend, seed_file

pytestmark = pytest.mark.django_db


@pytest.fixture
def manager():
    return StorageManager(InMemoryStorageBackend(organization_prefix=""))


def _bin(row: StorageFile) -> StorageFile:
    StorageFile.all_objects.filter(pk=row.pk).update(
        active=False, soft_deleted_at=timezone.now(), soft_delete_batch=uuid.uuid4()
    )
    return StorageFile.all_objects.get(pk=row.pk)


def _binned_file(org, path: str, size: int = 3) -> StorageFile:
    """A recycle-bin row with no live object, as a soft delete leaves it."""
    parent, _, name = path.rpartition("/")
    row = StorageFile.objects.create(
        org=org, path=path, name=name, item_type="file", size=size, parent_path=f"{parent}/" if parent else ""
    )
    return _bin(row)


def _tree_paths(node) -> set[str]:
    paths = {node.path}
    for child in getattr(node, "children", None) or []:
        paths |= _tree_paths(child)
    return paths


class TestManagerReads:
    def test_list_hides_a_binned_file(self, manager, org):
        _binned_file(org, "gone.txt")
        seed_file(manager._backend, org.id, "kept.txt", b"abc")

        assert [item.name for item in manager.list_(org.id, "")] == ["kept.txt"]

    def test_a_folder_whose_only_child_is_binned_is_empty(self, manager, org):
        manager.mkdir(org.id, "docs")
        _binned_file(org, "docs/gone.txt")

        folder = next(item for item in manager.list_(org.id, "") if item.name == "docs")
        assert folder.is_empty is True

    def test_download_and_info_refuse_a_binned_file(self, manager, org):
        _binned_file(org, "gone.txt")

        with pytest.raises(FileNotFoundError):
            manager.download(org.id, "gone.txt")
        with pytest.raises(FileNotFoundError):
            manager.info(org.id, "gone.txt")

    def test_tree_and_search_skip_a_binned_file(self, manager, org):
        _binned_file(org, "gone.txt")

        tree, _ = manager.list_tree(org.id)
        assert "gone.txt" not in _tree_paths(tree)
        assert manager.search(org.id, "gone")[1] == 0


class TestSyncWrites:
    def test_upload_makes_a_new_live_row_beside_a_binned_one(self, org):
        binned = _binned_file(org, "a.txt")

        StorageFileSync.on_upload(org.id, "a.txt", size=3)

        assert StorageFile.objects.get(org=org, path="a.txt").pk != binned.pk
        assert StorageFile.deleted_objects.filter(pk=binned.pk).exists()

    def test_runtime_delete_keeps_the_binned_row(self, org):
        binned = _binned_file(org, "a.txt")
        StorageFileSync.on_upload(org.id, "a.txt", size=3)

        StorageFileSync.on_delete(org.id, "a.txt")

        assert not StorageFile.objects.filter(org=org, path="a.txt").exists()
        assert StorageFile.deleted_objects.filter(pk=binned.pk).exists()

    def test_moving_a_folder_leaves_its_binned_rows_in_place(self, org):
        StorageFileSync.on_mkdir(org.id, "docs/")
        binned = _binned_file(org, "docs/x.txt")

        StorageFileSync.on_move(org.id, "docs/", "archive/")

        assert StorageFile.all_objects.get(pk=binned.pk).path == "docs/x.txt"


def test_binned_files_count_toward_the_quota(org):
    StorageFileSync.on_upload(org.id, "live.txt", size=5)
    _binned_file(org, "gone.txt", size=7)

    assert org_used_bytes(org.id) == 12


class TestReconcilerKeepsTheBin:
    def test_rerun_on_the_same_listing_changes_nothing(self, org, fake_backend):
        fake_backend.put_bytes(f"org_{org.id}/a.txt", b"abc")
        reconciler = StorageReconciler(fake_backend)
        reconciler.reconcile_tree(org.id, "")
        count = StorageFile.all_objects.filter(org=org).count()

        reconciler.reconcile_tree(org.id, "")

        assert StorageFile.all_objects.filter(org=org).count() == count

    def test_a_changed_size_is_updated(self, org, fake_backend):
        fake_backend.put_bytes(f"org_{org.id}/a.txt", b"abc")
        reconciler = StorageReconciler(fake_backend)
        reconciler.reconcile_tree(org.id, "")
        fake_backend.put_bytes(f"org_{org.id}/a.txt", b"abcdefg")

        reconciler.reconcile_tree(org.id, "")

        assert StorageFile.objects.get(org=org, path="a.txt").size == 7

    def test_a_binned_row_is_not_swept(self, org, fake_backend):
        binned = _binned_file(org, "docs/a.txt")

        StorageReconciler(fake_backend).reconcile_tree(org.id, "")

        assert StorageFile.deleted_objects.filter(pk=binned.pk).exists()

    def test_a_live_object_at_a_binned_path_gets_its_own_row(self, org, fake_backend):
        _binned_file(org, "docs/a.txt")
        fake_backend.put_bytes(f"org_{org.id}/docs/a.txt", b"new")

        StorageReconciler(fake_backend).reconcile_tree(org.id, "")

        assert StorageFile.all_objects.filter(org=org, path="docs/a.txt").count() == 2
        assert StorageFile.objects.filter(org=org, path="docs/a.txt").count() == 1

    def test_trash_objects_are_not_indexed(self, org, fake_backend):
        fake_backend.put_bytes(f"org_{org.id}/.recycle-bin/{uuid.uuid4()}/docs/a.txt", b"old")

        StorageReconciler(fake_backend).reconcile_tree(org.id, "")

        assert not StorageFile.all_objects.filter(org=org, path__startswith=".recycle-bin").exists()

    def test_reconciling_the_trash_folder_is_refused(self, org, fake_backend):
        with pytest.raises(ValueError):
            StorageReconciler(fake_backend).reconcile_tree(org.id, ".recycle-bin/")


def test_prune_keeps_binned_rows(org):
    # A binned file has no live object, so a prune that saw it would wipe the bin.
    binned = _binned_file(org, "gone.txt")
    orphan = StorageFile.objects.create(org=org, path="orphan.txt", name="orphan.txt", item_type="file")
    backend = InMemoryStorageBackend(organization_prefix="")

    with patch(
        "tables.services.storage_service.get_storage_manager",
        return_value=SimpleNamespace(_backend=backend),
    ):
        call_command("prune_storage_files", "--org-id", str(org.id))

    assert StorageFile.deleted_objects.filter(pk=binned.pk).exists()
    assert not StorageFile.all_objects.filter(pk=orphan.pk).exists()
