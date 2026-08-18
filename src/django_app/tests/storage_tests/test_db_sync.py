import pytest
from django.utils import timezone

from tables.models import Organization, StorageFile
from tables.services.storage_service.db_sync import StorageFileSync, _parent_of


pytestmark = pytest.mark.django_db


class TestParentOf:
    def test_nested_file(self):
        assert _parent_of("a/b/c.txt") == "a/b/"

    def test_root_file(self):
        assert _parent_of("c.txt") == ""

    def test_nested_folder(self):
        assert _parent_of("a/b/") == "a/"

    def test_single_level_folder(self):
        assert _parent_of("a/") == ""


class TestOnUpload:
    def test_on_upload_creates_storage_file(self, org):
        StorageFileSync.on_upload(org.id, "docs/report.txt")
        assert StorageFile.objects.filter(org=org, path="docs/report.txt").exists()

    def test_on_upload_is_idempotent(self, org):
        StorageFileSync.on_upload(org.id, "docs/report.txt")
        StorageFileSync.on_upload(org.id, "docs/report.txt")
        assert StorageFile.objects.filter(org=org, path="docs/report.txt").count() == 1

    def test_on_upload_stores_size_when_provided(self, org):
        StorageFileSync.on_upload(org.id, "data.csv", size=1024)
        row = StorageFile.objects.get(org=org, path="data.csv")
        assert row.size == 1024

    def test_on_upload_does_not_overwrite_size_with_none(self, org):
        StorageFileSync.on_upload(org.id, "data.csv", size=512)
        StorageFileSync.on_upload(org.id, "data.csv")
        row = StorageFile.objects.get(org=org, path="data.csv")
        assert row.size == 512

    def test_on_upload_creates_ancestor_folder_rows(self, org):
        StorageFileSync.on_upload(org.id, "a/b/file.txt")
        assert StorageFile.objects.filter(
            org=org, path="a/", item_type="folder"
        ).exists()
        assert StorageFile.objects.filter(
            org=org, path="a/b/", item_type="folder"
        ).exists()

    def test_on_upload_sets_parent_path(self, org):
        StorageFileSync.on_upload(org.id, "x/y/z.txt")
        row = StorageFile.objects.get(org=org, path="x/y/z.txt")
        assert row.parent_path == "x/y/"

    def test_on_upload_sets_item_type_file(self, org):
        StorageFileSync.on_upload(org.id, "plain.txt")
        row = StorageFile.objects.get(org=org, path="plain.txt")
        assert row.item_type == "file"


class TestOnMkdir:
    def test_on_mkdir_creates_folder_row(self, org):
        StorageFileSync.on_mkdir(org.id, "newdir")
        assert StorageFile.objects.filter(
            org=org, path="newdir/", item_type="folder"
        ).exists()

    def test_on_mkdir_creates_ancestor_folders(self, org):
        StorageFileSync.on_mkdir(org.id, "a/b/c")
        assert StorageFile.objects.filter(org=org, path="a/").exists()
        assert StorageFile.objects.filter(org=org, path="a/b/").exists()
        assert StorageFile.objects.filter(org=org, path="a/b/c/").exists()

    def test_on_mkdir_is_idempotent(self, org):
        StorageFileSync.on_mkdir(org.id, "dir")
        StorageFileSync.on_mkdir(org.id, "dir")
        assert StorageFile.objects.filter(org=org, path="dir/").count() == 1


class TestOnDelete:
    def test_on_delete_removes_exact_path(self, org):
        StorageFile.objects.create(org=org, path="old.txt", name="old.txt")
        StorageFileSync.on_delete(org.id, "old.txt")
        assert not StorageFile.objects.filter(org=org, path="old.txt").exists()

    def test_on_delete_removes_folder_prefix_when_no_exact_match(self, org):
        StorageFile.objects.create(org=org, path="docs/a.txt", name="a.txt")
        StorageFile.objects.create(org=org, path="docs/b.txt", name="b.txt")
        StorageFileSync.on_delete(org.id, "docs")
        assert StorageFile.objects.filter(org=org).count() == 0

    def test_on_delete_noop_when_path_missing(self, org):
        StorageFileSync.on_delete(org.id, "nonexistent.txt")


class TestOnMove:
    def test_on_move_updates_single_file_path(self, org):
        StorageFile.objects.create(org=org, path="old.txt", name="old.txt")
        StorageFileSync.on_move(org.id, "old.txt", "new.txt")
        assert not StorageFile.objects.filter(org=org, path="old.txt").exists()
        assert StorageFile.objects.filter(org=org, path="new.txt").exists()

    def test_on_move_updates_parent_path_for_single_file(self, org):
        StorageFile.objects.create(
            org=org, path="dir/old.txt", name="old.txt", parent_path="dir/"
        )
        StorageFileSync.on_move(org.id, "dir/old.txt", "other/new.txt")
        row = StorageFile.objects.get(org=org, path="other/new.txt")
        assert row.parent_path == "other/"

    def test_on_move_bulk_updates_folder_children(self, org):
        StorageFile.objects.create(org=org, path="old/a.txt", name="a.txt")
        StorageFile.objects.create(org=org, path="old/sub/b.txt", name="b.txt")
        StorageFileSync.on_move(org.id, "old", "new")
        paths = set(StorageFile.objects.filter(org=org).values_list("path", flat=True))
        assert paths == {"new/a.txt", "new/sub/b.txt"}

    def test_on_move_recomputes_parent_path_for_folder_children(self, org):
        StorageFile.objects.create(
            org=org, path="old/a.txt", name="a.txt", parent_path="old/"
        )
        StorageFile.objects.create(
            org=org, path="old/sub/b.txt", name="b.txt", parent_path="old/sub/"
        )
        StorageFileSync.on_move(org.id, "old", "new")
        row_a = StorageFile.objects.get(org=org, path="new/a.txt")
        row_b = StorageFile.objects.get(org=org, path="new/sub/b.txt")
        assert row_a.parent_path == "new/"
        assert row_b.parent_path == "new/sub/"

    def test_on_move_folder_into_existing_sibling_folder_does_not_collide(self, org):
        """Moving 'docs' into an already-present 'archive/' folder must not
        touch 'archive/' itself and must not raise an IntegrityError."""
        StorageFile.objects.create(
            org=org, path="archive/", name="archive", item_type="folder"
        )
        StorageFile.objects.create(
            org=org, path="docs/", name="docs", item_type="folder", parent_path=""
        )
        StorageFile.objects.create(
            org=org, path="docs/a.txt", name="a.txt", parent_path="docs/"
        )

        StorageFileSync.on_move(org.id, "docs", "archive/docs/")

        assert StorageFile.objects.filter(org=org, path="archive/").exists()
        assert StorageFile.objects.filter(
            org=org, path="archive/docs/", item_type="folder"
        ).exists()
        assert StorageFile.objects.filter(org=org, path="archive/docs/a.txt").exists()
        assert not StorageFile.objects.filter(org=org, path="docs/").exists()
        assert not StorageFile.objects.filter(org=org, path="docs/a.txt").exists()

    def test_on_move_folder_recomputes_name_for_deduped_destination(self, org):
        StorageFile.objects.create(
            org=org, path="docs/", name="docs", item_type="folder"
        )
        StorageFile.objects.create(
            org=org, path="docs/a.txt", name="a.txt", parent_path="docs/"
        )

        StorageFileSync.on_move(org.id, "docs", "archive/docs (1)/")

        row = StorageFile.objects.get(org=org, path="archive/docs (1)/")
        assert row.name == "docs (1)"

    def test_on_move_folder_branch_preserves_size_and_modified(self, org):
        modified = timezone.now()
        StorageFile.objects.create(
            org=org, path="docs/", name="docs", item_type="folder"
        )
        StorageFile.objects.create(
            org=org,
            path="docs/a.txt",
            name="a.txt",
            parent_path="docs/",
            size=42,
            s3_modified=modified,
        )

        StorageFileSync.on_move(org.id, "docs", "archive/docs/")

        row = StorageFile.objects.get(org=org, path="archive/docs/a.txt")
        assert row.size == 42
        assert row.s3_modified == modified


class TestOnCopy:
    def test_on_copy_creates_all_paths(self, org):
        StorageFileSync.on_copy(org.id, ["copy/a.txt", "copy/b.txt"])
        assert StorageFile.objects.filter(org=org).count() == 3

    def test_on_copy_ignores_duplicate_conflicts(self, org):
        StorageFile.objects.create(org=org, path="dup.txt", name="dup.txt")
        StorageFileSync.on_copy(org.id, ["dup.txt", "new.txt"])
        assert StorageFile.objects.filter(org=org).count() == 2

    def test_on_copy_sets_item_type_file(self, org):
        StorageFileSync.on_copy(org.id, ["dest/copy.txt"])
        row = StorageFile.objects.get(org=org, path="dest/copy.txt")
        assert row.item_type == "file"
        assert row.parent_path == "dest/"

    def test_on_copy_creates_folder_row_and_ancestors(self, org):
        StorageFileSync.on_copy(org.id, ["dest/docs/", "dest/docs/a.txt"])
        assert StorageFile.objects.filter(
            org=org, path="dest/docs/", item_type="folder"
        ).exists()
        assert StorageFile.objects.filter(
            org=org, path="dest/", item_type="folder"
        ).exists()
        assert StorageFile.objects.filter(
            org=org, path="dest/docs/a.txt", item_type="file"
        ).exists()
        assert StorageFile.objects.filter(org=org).count() == 3


class TestCrossOrg:
    def test_on_move_cross_org_file_deletes_source_creates_dest(self, org, second_org):
        StorageFile.objects.create(org=org, path="moved.txt")
        StorageFileSync.on_move_cross_org(
            org.id, "moved.txt", second_org.id, "landed.txt"
        )
        assert not StorageFile.objects.filter(org=org, path="moved.txt").exists()
        assert StorageFile.objects.filter(org=second_org, path="landed.txt").exists()

    def test_on_move_cross_org_file_preserves_size_and_modified(self, org, second_org):
        modified = timezone.now()
        StorageFile.objects.create(
            org=org, path="moved.txt", size=99, s3_modified=modified
        )
        StorageFileSync.on_move_cross_org(
            org.id, "moved.txt", second_org.id, "landed.txt"
        )
        row = StorageFile.objects.get(org=second_org, path="landed.txt")
        assert row.size == 99
        assert row.s3_modified == modified

    def test_on_move_cross_org_folder_translates_children_and_deletes_source(
        self, org, second_org
    ):
        StorageFile.objects.create(
            org=org, path="docs/", name="docs", item_type="folder"
        )
        StorageFile.objects.create(
            org=org, path="docs/a.txt", name="a.txt", parent_path="docs/"
        )
        StorageFile.objects.create(
            org=org, path="docs/sub/b.txt", name="b.txt", parent_path="docs/sub/"
        )

        StorageFileSync.on_move_cross_org(
            org.id, "docs", second_org.id, "archive/docs/"
        )

        assert StorageFile.objects.filter(org=org, path__startswith="docs").count() == 0
        assert StorageFile.objects.filter(
            org=second_org, path="archive/docs/", item_type="folder"
        ).exists()
        assert StorageFile.objects.filter(
            org=second_org, path="archive/docs/a.txt"
        ).exists()
        assert StorageFile.objects.filter(
            org=second_org, path="archive/docs/sub/b.txt"
        ).exists()
        assert StorageFile.objects.filter(
            org=second_org, path="archive/", item_type="folder"
        ).exists()
