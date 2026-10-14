import pytest

from tables.models import StorageFile
from tables.services.storage_service.dataclasses import (
    FileInfo,
    FolderInfo,
)
from tables.services.storage_service.manager import StorageManager


from tests.storage_tests.storage_writes import store_object


@pytest.fixture
def manager(fake_backend):
    return StorageManager(fake_backend)


def _keys(backend, org):
    return sorted(key.removeprefix(f"org_{org.id}/") for key in backend.list_all_keys(f"org_{org.id}"))


def _rows(org):
    return dict(StorageFile.objects.filter(org=org).values_list("path", "item_type"))


@pytest.mark.django_db
class TestWrites:
    """Every write changes storage under the org's prefix and keeps the file rows in step."""

    def test_mkdir_creates_the_folder_and_its_row_authored_by_the_user(self, manager, fake_backend, org, org_user):
        manager.mkdir(org.id, "docs", user=org_user.user)

        assert fake_backend.exists(f"org_{org.id}/docs/")
        folder = StorageFile.objects.get(org=org, path="docs/")
        assert (folder.item_type, folder.created_by) == ("folder", org_user.user)

    def test_delete_removes_the_object_and_its_row(self, manager, fake_backend, org, org_user):
        store_object(fake_backend, org.id, "old.txt", b"x")

        manager.delete(org.id, "old.txt")

        assert _keys(fake_backend, org) == []
        assert _rows(org) == {}

    def test_move_puts_the_file_inside_the_destination_and_moves_its_row(self, manager, fake_backend, org, org_user):
        store_object(fake_backend, org.id, "a.txt", b"x")
        manager.mkdir(org.id, "dest")

        manager.move(org.id, "a.txt", "dest", user=org_user.user)

        assert fake_backend.download(f"org_{org.id}/dest/a.txt") == b"x"
        assert not fake_backend.exists(f"org_{org.id}/a.txt")
        assert set(_rows(org)) == {"dest/", "dest/a.txt"}

    def test_rename_moves_the_file_and_its_row(self, manager, fake_backend, org, org_user):
        store_object(fake_backend, org.id, "old.txt", b"x")

        manager.rename(org.id, "old.txt", "new.txt", user=org_user.user)

        assert _keys(fake_backend, org) == ["new.txt"]
        assert set(_rows(org)) == {"new.txt"}

    def test_rename_onto_an_existing_file_changes_nothing(self, manager, fake_backend, org, org_user):
        store_object(fake_backend, org.id, "old.txt", b"old")
        store_object(fake_backend, org.id, "new.txt", b"new")

        with pytest.raises(FileExistsError):
            manager.rename(org.id, "old.txt", "new.txt")

        assert fake_backend.download(f"org_{org.id}/new.txt") == b"new"
        assert set(_rows(org)) == {"old.txt", "new.txt"}

    def test_copy_records_every_copied_file_and_folder(self, manager, fake_backend, org, org_user):
        store_object(fake_backend, org.id, "src/a.txt", b"a")
        store_object(fake_backend, org.id, "src/b.txt", b"bb")
        manager.mkdir(org.id, "dest")

        manager.copy(org.id, "src", "dest", user=org_user.user)

        assert fake_backend.download(f"org_{org.id}/dest/src/b.txt") == b"bb"
        copied = StorageFile.objects.filter(org=org, path__startswith="dest/src/")
        assert {(row.path, row.size) for row in copied if row.item_type == "file"} == {
            ("dest/src/a.txt", 1), ("dest/src/b.txt", 2),
        }
        assert all(row.created_by == org_user.user for row in copied)
        assert fake_backend.exists(f"org_{org.id}/src/a.txt")

    def test_info_reports_the_path_without_the_org_prefix(self, manager, fake_backend, org, org_user):
        store_object(fake_backend, org.id, "docs/f.txt", b"hello")

        result = manager.info(org.id, "docs/f.txt")

        assert isinstance(result, FileInfo)
        assert (result.path, result.size) == ("docs/f.txt", 5)


@pytest.mark.django_db
class TestCrossOrg:
    def test_copy_to_another_org_records_the_copies_authored_by_the_copier_and_keeps_the_source(
        self, manager, fake_backend, org, org_user, second_org
    ):
        store_object(fake_backend, org.id, "src.txt", b"abc", user=org_user.user)
        manager.mkdir(second_org.id, "inbox")

        manager.copy_cross_org(org.id, "src.txt", second_org.id, "inbox", user=org_user.user)

        assert fake_backend.download(f"org_{second_org.id}/inbox/src.txt") == b"abc"
        copy = StorageFile.objects.get(org=second_org, path="inbox/src.txt")
        assert (copy.size, copy.created_by) == (3, org_user.user)
        assert _keys(fake_backend, org) == ["src.txt"]

    def test_move_to_another_org_drops_an_author_who_is_not_a_member_and_removes_the_source(
        self, manager, fake_backend, org, org_user, second_org
    ):
        store_object(fake_backend, org.id, "src.txt", b"abc", user=org_user.user)
        manager.mkdir(second_org.id, "inbox")

        manager.move_cross_org(org.id, "src.txt", second_org.id, "inbox", user=org_user.user)

        moved = StorageFile.objects.get(org=second_org, path="inbox/src.txt")
        assert moved.created_by is None
        assert _keys(fake_backend, org) == []
        assert _rows(org) == {}


@pytest.mark.django_db
class TestListTreeManager:
    @pytest.fixture
    def db_manager(self, fake_backend, org, org_user):
        """Manager backed by an InMemoryStorageBackend (no mock) with DB rows seeded."""
        from tables.models import StorageFile

        StorageFile.objects.bulk_create(
            [
                StorageFile(
                    org=org,
                    path="reports/",
                    name="reports",
                    item_type="folder",
                    parent_path="",
                ),
                StorageFile(
                    org=org,
                    path="reports/q1.pdf",
                    name="q1.pdf",
                    item_type="file",
                    size=10,
                    parent_path="reports/",
                ),
            ]
        )
        from tables.services.storage_service.manager import StorageManager

        return StorageManager(fake_backend)

    def test_list_tree_builds_tree_from_db_rows(self, db_manager, org, org_user):
        root, truncated = db_manager.list_tree(org.id, "reports")
        assert root.path == "reports/"
        assert root.children[0].path == "reports/q1.pdf"
        assert truncated is False

    def test_list_tree_orders_children_folders_first_then_case_insensitive_alphabetical(
        self, fake_backend, org, org_user
    ):
        StorageFile.objects.bulk_create(
            [
                StorageFile(
                    org=org,
                    path="root/",
                    name="root",
                    item_type="folder",
                    parent_path="",
                ),
                StorageFile(
                    org=org,
                    path="root/alpha/",
                    name="alpha",
                    item_type="folder",
                    parent_path="root/",
                ),
                StorageFile(
                    org=org,
                    path="root/Beta/",
                    name="Beta",
                    item_type="folder",
                    parent_path="root/",
                ),
                StorageFile(
                    org=org,
                    path="root/b.txt",
                    name="b.txt",
                    item_type="file",
                    parent_path="root/",
                    size=1,
                ),
                StorageFile(
                    org=org,
                    path="root/Zeta.txt",
                    name="Zeta.txt",
                    item_type="file",
                    parent_path="root/",
                    size=1,
                ),
            ]
        )
        manager = StorageManager(fake_backend)
        root, _ = manager.list_tree(org.id, "root")
        assert [child.name for child in root.children] == [
            "alpha",
            "Beta",
            "b.txt",
            "Zeta.txt",
        ]
        assert [child.type for child in root.children] == [
            "folder",
            "folder",
            "file",
            "file",
        ]


@pytest.mark.django_db
class TestListManager:
    @pytest.fixture
    def db_manager(self, fake_backend, org, org_user):
        from tables.models import StorageFile
        from tables.services.storage_service.manager import StorageManager
        from django.utils import timezone

        modified = timezone.now()
        StorageFile.objects.bulk_create(
            [
                StorageFile(
                    org=org,
                    path="docs/",
                    name="docs",
                    item_type="folder",
                    parent_path="",
                    size=None,
                    s3_modified=None,
                ),
                StorageFile(
                    org=org,
                    path="root.txt",
                    name="root.txt",
                    item_type="file",
                    parent_path="",
                    size=42,
                    s3_modified=modified,
                ),
                StorageFile(
                    org=org,
                    path="docs/inner.txt",
                    name="inner.txt",
                    item_type="file",
                    parent_path="docs/",
                    size=7,
                    s3_modified=modified,
                ),
            ]
        )
        return StorageManager(fake_backend)

    def test_list_root_returns_folder_and_file(self, db_manager, org, org_user):
        items = db_manager.list_(org.id, "")
        names = {i.name for i in items}
        assert "docs" in names
        assert "root.txt" in names

    def test_folder_is_not_empty_when_it_has_children(self, db_manager, org, org_user):
        items = db_manager.list_(org.id, "")
        docs = next(i for i in items if i.name == "docs")
        assert docs.is_empty is False

    def test_file_is_empty_false(self, db_manager, org, org_user):
        items = db_manager.list_(org.id, "")
        txt = next(i for i in items if i.name == "root.txt")
        assert txt.is_empty is False
        assert txt.size == 42

    def test_folder_modified_is_none_when_s3_modified_null(
        self, db_manager, org, org_user
    ):
        items = db_manager.list_(org.id, "")
        docs = next(i for i in items if i.name == "docs")
        assert docs.modified is None

    def test_list_with_prefix_returns_only_direct_children(
        self, db_manager, org, org_user
    ):
        items = db_manager.list_(org.id, "docs")
        assert len(items) == 1
        assert items[0].name == "inner.txt"

    def test_list_orders_folders_first_then_case_insensitive_alphabetical(
        self, fake_backend, org, org_user
    ):
        StorageFile.objects.bulk_create(
            [
                StorageFile(
                    org=org,
                    path="alpha/",
                    name="alpha",
                    item_type="folder",
                    parent_path="",
                ),
                StorageFile(
                    org=org,
                    path="Beta/",
                    name="Beta",
                    item_type="folder",
                    parent_path="",
                ),
                StorageFile(
                    org=org,
                    path="b.txt",
                    name="b.txt",
                    item_type="file",
                    parent_path="",
                    size=1,
                ),
                StorageFile(
                    org=org,
                    path="Zeta.txt",
                    name="Zeta.txt",
                    item_type="file",
                    parent_path="",
                    size=1,
                ),
            ]
        )
        manager = StorageManager(fake_backend)
        items = manager.list_(org.id, "")
        assert [i.name for i in items] == ["alpha", "Beta", "b.txt", "Zeta.txt"]
        assert [i.type for i in items] == ["folder", "folder", "file", "file"]


@pytest.mark.django_db
class TestInfoManager:
    @pytest.fixture
    def db_manager(self, fake_backend, org, org_user):
        from tables.models import StorageFile
        from tables.services.storage_service.manager import StorageManager
        from django.utils import timezone

        modified = timezone.now()
        StorageFile.objects.bulk_create(
            [
                StorageFile(
                    org=org,
                    path="docs/",
                    name="docs",
                    item_type="folder",
                    parent_path="",
                    size=None,
                    s3_modified=modified,
                ),
                StorageFile(
                    org=org,
                    path="docs/note.txt",
                    name="note.txt",
                    item_type="file",
                    parent_path="docs/",
                    size=99,
                    s3_modified=modified,
                ),
            ]
        )
        return StorageManager(fake_backend)

    def test_info_returns_file_info_for_file_path(self, db_manager, org, org_user):
        result = db_manager.info(org.id, "docs/note.txt")
        assert isinstance(result, FileInfo)
        assert result.name == "note.txt"
        assert result.size == 99

    def test_info_returns_folder_info_for_folder_path(self, db_manager, org, org_user):
        result = db_manager.info(org.id, "docs")
        assert isinstance(result, FolderInfo)
        assert result.path == "docs/"

    def test_info_raises_for_missing_path(self, db_manager, org, org_user):
        with pytest.raises(FileNotFoundError):
            db_manager.info(org.id, "nonexistent.txt")


@pytest.mark.django_db
class TestSearchManager:
    @pytest.fixture
    def seeded(self, org, second_org, org_user):
        StorageFile.objects.bulk_create(
            [
                StorageFile(
                    org=org,
                    path="reports/q1_report.pdf",
                    name="q1_report.pdf",
                    item_type="file",
                ),
                StorageFile(
                    org=org,
                    path="reports/q2_report.pdf",
                    name="q2_report.pdf",
                    item_type="file",
                ),
                StorageFile(
                    org=org,
                    path="archive/note.txt",
                    name="note.txt",
                    item_type="file",
                ),
                StorageFile(
                    org=org,
                    path="other/report_draft.md",
                    name="report_draft.md",
                    item_type="file",
                ),
                StorageFile(
                    org=second_org,
                    path="reports/q1_report.pdf",
                    name="q1_report.pdf",
                    item_type="file",
                ),
                StorageFile(
                    org=org,
                    path="reports/",
                    name="reports",
                    item_type="folder",
                ),
            ]
        )

    def test_search_finds_filename_substring(
        self, storage_manager, org, org_user, seeded
    ):
        results, total = storage_manager.search(org.id, q="report")
        assert total == 3
        names = [r["name"] for r in results]
        assert "q1_report.pdf" in names
        assert "note.txt" not in names

    def test_search_is_case_insensitive(self, storage_manager, org, org_user, seeded):
        _, total = storage_manager.search(org.id, q="REPORT")
        assert total == 3

    def test_search_scoped_to_path(self, storage_manager, org, org_user, seeded):
        _, total = storage_manager.search(org.id, q="report", path="reports/")
        assert total == 2

    def test_search_excludes_other_orgs(
        self, storage_manager, org, second_org, org_user, seeded
    ):
        _, total = storage_manager.search(org.id, q="q1_report")
        assert total == 1

    def test_search_excludes_folder_rows(self, storage_manager, org, org_user, seeded):
        results, total = storage_manager.search(org.id, q="reports")
        names = [r["name"] for r in results]
        assert "reports" not in names

    def test_search_pagination(self, storage_manager, org, org_user, seeded):
        page1, total = storage_manager.search(org.id, q="report", limit=2, offset=0)
        page2, _ = storage_manager.search(org.id, q="report", limit=2, offset=2)
        assert len(page1) == 2
        assert len(page2) == 1
        assert total == 3
        assert page1[0]["path"] != page2[0]["path"]

    def test_search_results_include_id(self, storage_manager, org, org_user, seeded):
        results, _ = storage_manager.search(org.id, q="q1_report")
        assert len(results) == 1
        row = StorageFile.objects.get(org=org, path="reports/q1_report.pdf")
        assert results[0]["id"] == row.id


@pytest.mark.django_db
class TestStorageIdExposure:
    """Verify that list_(), info(), list_tree() carry the DB row id through."""

    @pytest.fixture
    def db_manager(self, fake_backend, org, org_user):
        from django.utils import timezone

        modified = timezone.now()
        StorageFile.objects.bulk_create(
            [
                StorageFile(
                    org=org,
                    path="docs/",
                    name="docs",
                    item_type="folder",
                    parent_path="",
                    size=None,
                    s3_modified=modified,
                ),
                StorageFile(
                    org=org,
                    path="docs/note.txt",
                    name="note.txt",
                    item_type="file",
                    parent_path="docs/",
                    size=50,
                    s3_modified=modified,
                ),
            ]
        )
        from tables.services.storage_service.manager import StorageManager

        return StorageManager(fake_backend)

    def test_list_file_item_carries_row_id(self, db_manager, org, org_user):
        items = db_manager.list_(org.id, "docs")
        file_item = next(i for i in items if i.name == "note.txt")
        expected_id = StorageFile.objects.get(org=org, path="docs/note.txt").id
        assert file_item.id == expected_id

    def test_list_folder_item_carries_row_id(self, db_manager, org, org_user):
        items = db_manager.list_(org.id, "")
        folder_item = next(i for i in items if i.name == "docs")
        expected_id = StorageFile.objects.get(org=org, path="docs/").id
        assert folder_item.id == expected_id

    def test_info_file_carries_row_id(self, db_manager, org, org_user):
        result = db_manager.info(org.id, "docs/note.txt")
        expected_id = StorageFile.objects.get(org=org, path="docs/note.txt").id
        assert result.id == expected_id

    def test_info_folder_carries_row_id(self, db_manager, org, org_user):
        result = db_manager.info(org.id, "docs")
        expected_id = StorageFile.objects.get(org=org, path="docs/").id
        assert result.id == expected_id

    def test_list_tree_leaf_file_carries_row_id(self, db_manager, org, org_user):
        root, _ = db_manager.list_tree(org.id, "docs")
        leaf = next(child for child in root.children if child.name == "note.txt")
        expected_id = StorageFile.objects.get(org=org, path="docs/note.txt").id
        assert leaf.id == expected_id

    def test_list_tree_leaf_folder_carries_row_id(self, db_manager, org, org_user):
        root, _ = db_manager.list_tree(org.id, "")
        folder_node = next(child for child in root.children if child.name == "docs")
        expected_id = StorageFile.objects.get(org=org, path="docs/").id
        assert folder_node.id == expected_id

    def test_list_tree_root_node_id_is_none(self, db_manager, org, org_user):
        root, _ = db_manager.list_tree(org.id, "docs")
        assert root.id is None
