import pytest

from tables.models import Organization, StorageFile
from tables.services.storage_service.db_sync import StorageFileSync


pytestmark = pytest.mark.django_db


class TestOnUpload:
    def test_on_upload_creates_storage_file(self, org):
        StorageFileSync.on_upload(org.id, "docs/report.txt")
        assert StorageFile.objects.filter(org=org, path="docs/report.txt").exists()

    def test_on_upload_is_idempotent(self, org):
        StorageFileSync.on_upload(org.id, "docs/report.txt")
        StorageFileSync.on_upload(org.id, "docs/report.txt")
        assert StorageFile.objects.filter(org=org, path="docs/report.txt").count() == 1


class TestOnDelete:
    def test_on_delete_removes_exact_path(self, org):
        StorageFile.objects.create(org=org, path="old.txt")
        StorageFileSync.on_delete(org.id, "old.txt")
        assert not StorageFile.objects.filter(org=org, path="old.txt").exists()

    def test_on_delete_removes_folder_prefix_when_no_exact_match(self, org):
        StorageFile.objects.create(org=org, path="docs/a.txt")
        StorageFile.objects.create(org=org, path="docs/b.txt")
        StorageFileSync.on_delete(org.id, "docs")
        assert StorageFile.objects.filter(org=org).count() == 0

    def test_on_delete_noop_when_path_missing(self, org):
        # Should not raise
        StorageFileSync.on_delete(org.id, "nonexistent.txt")


class TestOnMove:
    def test_on_move_updates_single_file_path(self, org):
        StorageFile.objects.create(org=org, path="old.txt")
        StorageFileSync.on_move(org.id, "old.txt", "new.txt")
        assert not StorageFile.objects.filter(org=org, path="old.txt").exists()
        assert StorageFile.objects.filter(org=org, path="new.txt").exists()

    def test_on_move_bulk_updates_folder_children(self, org):
        StorageFile.objects.create(org=org, path="old/a.txt")
        StorageFile.objects.create(org=org, path="old/sub/b.txt")
        StorageFileSync.on_move(org.id, "old", "new")
        paths = set(StorageFile.objects.filter(org=org).values_list("path", flat=True))
        assert paths == {"new/a.txt", "new/sub/b.txt"}


class TestOnCopy:
    def test_on_copy_creates_all_paths(self, org):
        StorageFileSync.on_copy(org.id, ["copy/a.txt", "copy/b.txt"])
        assert StorageFile.objects.filter(org=org).count() == 2

    def test_on_copy_ignores_duplicate_conflicts(self, org):
        StorageFile.objects.create(org=org, path="dup.txt")
        StorageFileSync.on_copy(org.id, ["dup.txt", "new.txt"])
        assert StorageFile.objects.filter(org=org).count() == 2


class TestCrossOrg:
    def test_on_move_cross_org_deletes_source_creates_dest(self, org, second_org):
        StorageFile.objects.create(org=org, path="moved.txt")
        StorageFileSync.on_move_cross_org(
            org.id, "moved.txt", second_org.id, "landed.txt"
        )
        assert not StorageFile.objects.filter(org=org, path="moved.txt").exists()
        assert StorageFile.objects.filter(org=second_org, path="landed.txt").exists()

    def test_on_copy_cross_org_creates_in_dest(self, second_org):
        StorageFileSync.on_copy_cross_org(second_org.id, "copied.txt")
        assert StorageFile.objects.filter(org=second_org, path="copied.txt").exists()

    def test_on_copy_cross_org_is_idempotent(self, second_org):
        StorageFileSync.on_copy_cross_org(second_org.id, "copied.txt")
        StorageFileSync.on_copy_cross_org(second_org.id, "copied.txt")
        assert (
            StorageFile.objects.filter(org=second_org, path="copied.txt").count() == 1
        )
