"""
Regression flow tests for StorageManager backed by a real InMemoryStorageBackend,
real StorageFileSync, and a real DB.

Kept in its own module: test_storage_manager.py applies a module-wide autouse
patch that mocks StorageFileSync, which would defeat these tests.
"""

import pytest

from tables.exceptions import RangeNotSatisfiable
from tables.models import StorageFile
from tables.services.storage_service.manager import StorageManager
from tests.storage_tests.in_memory_backend import InMemoryStorageBackend, seed_file


pytestmark = pytest.mark.django_db


@pytest.fixture
def manager():
    return StorageManager(InMemoryStorageBackend(organization_prefix=""))


class TestMoveFlows:
    def test_move_file_into_folder_creates_row_at_nested_path(
        self, manager, org, org_user
    ):
        manager.mkdir(org.id, "archive")
        seed_file(manager._backend, org.id, "report.txt", b"data")

        manager.move(org.id, "report.txt", "archive")

        row = StorageFile.objects.get(org=org, path="archive/report.txt")
        assert row.name == "report.txt"
        assert not StorageFile.objects.filter(org=org, path="report.txt").exists()

    def test_move_file_into_folder_with_name_collision_dedupes(
        self, manager, org, org_user
    ):
        manager.mkdir(org.id, "archive")
        seed_file(manager._backend, org.id, "archive/report.txt", b"existing")
        seed_file(manager._backend, org.id, "report.txt", b"incoming")

        manager.move(org.id, "report.txt", "archive")

        assert StorageFile.objects.filter(
            org=org, path="archive/report (1).txt"
        ).exists()
        assert StorageFile.objects.filter(org=org, path="archive/report.txt").exists()

    def test_move_folder_into_folder_creates_nested_rows_and_keeps_target(
        self, manager, org, org_user
    ):
        manager.mkdir(org.id, "archive")
        manager.mkdir(org.id, "docs")
        seed_file(manager._backend, org.id, "docs/a.txt", b"a")

        manager.move(org.id, "docs", "archive")

        assert StorageFile.objects.filter(org=org, path="archive/docs/").exists()
        assert StorageFile.objects.filter(org=org, path="archive/docs/a.txt").exists()
        assert StorageFile.objects.filter(org=org, path="archive/").exists()

    def test_move_folder_into_folder_with_name_collision_dedupes(
        self, manager, org, org_user
    ):
        manager.mkdir(org.id, "archive/docs")
        manager.mkdir(org.id, "docs")
        seed_file(manager._backend, org.id, "docs/a.txt", b"a")

        manager.move(org.id, "docs", "archive")

        assert StorageFile.objects.filter(org=org, path="archive/docs (1)/").exists()
        assert StorageFile.objects.filter(
            org=org, path="archive/docs (1)/a.txt"
        ).exists()
        assert StorageFile.objects.filter(org=org, path="archive/docs/").exists()


class TestCopyFlow:
    def test_copy_folder_creates_db_rows_visible_via_list_and_tree(
        self, manager, org, org_user
    ):
        manager.mkdir(org.id, "docs")
        seed_file(manager._backend, org.id, "docs/a.txt", b"a")

        manager.copy(org.id, "docs", "")

        assert StorageFile.objects.filter(org=org, path="docs (1)/").exists()
        assert StorageFile.objects.filter(org=org, path="docs (1)/a.txt").exists()

        items = manager.list_(org.id, "")
        assert "docs (1)" in {item.name for item in items}

        root, _ = manager.list_tree(org.id, "docs (1)")
        assert root.children[0].name == "a.txt"


class TestRenameFlow:
    def test_rename_onto_existing_path_raises_and_leaves_db_unchanged(
        self, manager, org, org_user
    ):
        seed_file(manager._backend, org.id, "a.txt", b"a")
        seed_file(manager._backend, org.id, "b.txt", b"b")

        with pytest.raises(FileExistsError):
            manager.rename(org.id, "a.txt", "b.txt")

        assert StorageFile.objects.filter(org=org, path="a.txt").exists()
        assert StorageFile.objects.filter(org=org, path="b.txt").exists()


class TestDownloadFlow:
    def test_download_without_db_row_raises_file_not_found(
        self, manager, org, org_user
    ):
        manager._backend.put_bytes(f"org_{org.id}/stray.txt", b"stray")

        with pytest.raises(FileNotFoundError):
            manager.download(org.id, "stray.txt")

    def test_download_with_db_row_returns_bytes(self, manager, org, org_user):
        seed_file(manager._backend, org.id, "known.txt", b"known content")

        download = manager.download(org.id, "known.txt")

        assert download.content == b"known content"
        assert download.content_range is None

    @pytest.mark.parametrize(
        ("range_header", "content", "content_range"),
        [
            ("bytes=0-4", b"known", "bytes 0-4/13"),
            ("bytes=6-", b"content", "bytes 6-12/13"),
            ("bytes=6-999", b"content", "bytes 6-12/13"),
            # unsupported ranges (suffix, multi, reversed, other unit, huge) get the whole file
            ("bytes=-5", b"known content", None),
            ("bytes=0-1,4-5", b"known content", None),
            ("bytes=5-2", b"known content", None),
            ("items=0-4", b"known content", None),
            ("bytes=" + "9" * 5000 + "-", b"known content", None),
        ],
    )
    def test_download_range_returns_only_that_part(
        self, manager, org, org_user, range_header, content, content_range
    ):
        seed_file(manager._backend, org.id, "known.txt", b"known content")

        download = manager.download(org.id, "known.txt", range_header)

        assert download.content == content
        assert download.content_range == content_range

    def test_download_range_past_end_raises_not_satisfiable(self, manager, org, org_user):
        seed_file(manager._backend, org.id, "known.txt", b"known content")

        with pytest.raises(RangeNotSatisfiable) as exc_info:
            manager.download(org.id, "known.txt", "bytes=13-")
        assert exc_info.value.headers == {"Content-Range": "bytes */13"}

    def test_download_range_follows_the_object_not_a_stale_row_size(
        self, manager, org, org_user
    ):
        seed_file(manager._backend, org.id, "known.txt", b"short")
        # An agent write replaces the object without touching the row's size.
        manager._backend.put_bytes(f"org_{org.id}/known.txt", b"much longer content")

        download = manager.download(org.id, "known.txt", "bytes=0-")

        assert download.content == b"much longer content"
        assert download.content_range == "bytes 0-18/19"

    def test_download_range_of_another_org_file_raises_file_not_found(
        self, manager, org, org_user, second_org
    ):
        seed_file(manager._backend, org.id, "known.txt", b"known content")

        with pytest.raises(FileNotFoundError):
            manager.download(second_org.id, "known.txt", "bytes=0-4")


class TestDownloadZipFlow:
    def test_zip_of_single_folder_has_folder_name_and_relative_entries(
        self, manager, org, org_user
    ):
        manager.mkdir(org.id, "folder")
        seed_file(manager._backend, org.id, "folder/tracked.txt", b"tracked")
        manager._backend.put_bytes(f"org_{org.id}/folder/stray.txt", b"untracked")

        zip_filename, chunks = manager.download_zip(org.id, ["folder"])
        zip_bytes = b"".join(chunks)

        import zipfile
        from io import BytesIO as IOBuf

        with zipfile.ZipFile(IOBuf(zip_bytes)) as archive:
            names = archive.namelist()

        assert zip_filename == "folder.zip"
        assert "tracked.txt" in names
        assert "folder/tracked.txt" not in names
        assert "stray.txt" not in names

    def test_zip_of_single_file_has_file_name_and_bare_entry(
        self, manager, org, org_user
    ):
        seed_file(manager._backend, org.id, "report.txt", b"payload")

        zip_filename, chunks = manager.download_zip(org.id, ["report.txt"])
        zip_bytes = b"".join(chunks)

        import zipfile
        from io import BytesIO as IOBuf

        with zipfile.ZipFile(IOBuf(zip_bytes)) as archive:
            names = archive.namelist()

        assert zip_filename == "report.txt.zip"
        assert names == ["report.txt"]

    def test_zip_of_multiple_paths_keeps_full_paths_and_download_zip_name(
        self, manager, org, org_user
    ):
        manager.mkdir(org.id, "folder")
        seed_file(manager._backend, org.id, "folder/tracked.txt", b"tracked")
        seed_file(manager._backend, org.id, "report.txt", b"payload")

        zip_filename, chunks = manager.download_zip(org.id, ["folder", "report.txt"])
        zip_bytes = b"".join(chunks)

        import zipfile
        from io import BytesIO as IOBuf

        with zipfile.ZipFile(IOBuf(zip_bytes)) as archive:
            names = archive.namelist()

        assert zip_filename == "download.zip"
        assert "folder/tracked.txt" in names
        assert "report.txt" in names

    def test_zip_raises_file_not_found_for_unknown_path(self, manager, org, org_user):
        with pytest.raises(FileNotFoundError):
            manager.download_zip(org.id, ["unknown/path"])


class TestCrossOrgMoveFlow:
    def test_move_cross_org_creates_dest_row_and_removes_source_row(
        self,
        manager,
        org,
        org_user,
        second_org,
        second_org_user,
    ):
        seed_file(manager._backend, org.id, "shared.txt", b"payload")
        manager.mkdir(second_org.id, "inbox")

        manager.move_cross_org(org.id, "shared.txt", second_org.id, "inbox")

        dest_row = StorageFile.objects.get(org=second_org, path="inbox/shared.txt")
        assert dest_row.name == "shared.txt"
        assert not StorageFile.objects.filter(org=org, path="shared.txt").exists()
