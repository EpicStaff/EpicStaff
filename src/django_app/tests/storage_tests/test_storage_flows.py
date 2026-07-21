"""
Regression flow tests for StorageManager backed by a real InMemoryStorageBackend,
real StorageFileSync, and a real DB.

Kept in its own module: test_storage_manager.py applies a module-wide autouse
patch that mocks StorageFileSync, which would defeat these tests.
"""

from io import BytesIO

import pytest

from tables.models import StorageFile
from tables.services.storage_service.manager import StorageManager
from tests.storage_tests.in_memory_backend import InMemoryStorageBackend


pytestmark = pytest.mark.django_db


@pytest.fixture
def manager():
    return StorageManager(InMemoryStorageBackend(organization_prefix=""))


class TestMoveFlows:
    def test_move_file_into_folder_creates_row_at_nested_path(
        self, manager, org, org_user
    ):
        manager.mkdir(org.id, "archive")
        manager.upload(org.id, "report.txt", BytesIO(b"data"))

        manager.move(org.id, "report.txt", "archive")

        row = StorageFile.objects.get(org=org, path="archive/report.txt")
        assert row.name == "report.txt"
        assert not StorageFile.objects.filter(org=org, path="report.txt").exists()

    def test_move_file_into_folder_with_name_collision_dedupes(
        self, manager, org, org_user
    ):
        manager.mkdir(org.id, "archive")
        manager.upload(org.id, "archive/report.txt", BytesIO(b"existing"))
        manager.upload(org.id, "report.txt", BytesIO(b"incoming"))

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
        manager.upload(org.id, "docs/a.txt", BytesIO(b"a"))

        manager.move(org.id, "docs", "archive")

        assert StorageFile.objects.filter(org=org, path="archive/docs/").exists()
        assert StorageFile.objects.filter(org=org, path="archive/docs/a.txt").exists()
        assert StorageFile.objects.filter(org=org, path="archive/").exists()

    def test_move_folder_into_folder_with_name_collision_dedupes(
        self, manager, org, org_user
    ):
        manager.mkdir(org.id, "archive/docs")
        manager.mkdir(org.id, "docs")
        manager.upload(org.id, "docs/a.txt", BytesIO(b"a"))

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
        manager.upload(org.id, "docs/a.txt", BytesIO(b"a"))

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
        manager.upload(org.id, "a.txt", BytesIO(b"a"))
        manager.upload(org.id, "b.txt", BytesIO(b"b"))

        with pytest.raises(FileExistsError):
            manager.rename(org.id, "a.txt", "b.txt")

        assert StorageFile.objects.filter(org=org, path="a.txt").exists()
        assert StorageFile.objects.filter(org=org, path="b.txt").exists()


class TestDownloadFlow:
    def test_download_without_db_row_raises_file_not_found(
        self, manager, org, org_user
    ):
        manager._backend.upload(f"org_{org.id}/stray.txt", BytesIO(b"stray"))

        with pytest.raises(FileNotFoundError):
            manager.download(org.id, "stray.txt")

    def test_download_with_db_row_returns_bytes(self, manager, org, org_user):
        manager.upload(org.id, "known.txt", BytesIO(b"known content"))

        assert manager.download(org.id, "known.txt") == b"known content"


class TestDownloadZipFlow:
    def test_zip_of_single_folder_has_folder_name_and_relative_entries(
        self, manager, org, org_user
    ):
        manager.mkdir(org.id, "folder")
        manager.upload(org.id, "folder/tracked.txt", BytesIO(b"tracked"))
        manager._backend.upload(f"org_{org.id}/folder/stray.txt", BytesIO(b"untracked"))

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
        manager.upload(org.id, "report.txt", BytesIO(b"payload"))

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
        manager.upload(org.id, "folder/tracked.txt", BytesIO(b"tracked"))
        manager.upload(org.id, "report.txt", BytesIO(b"payload"))

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
        manager.upload(org.id, "shared.txt", BytesIO(b"payload"))
        manager.mkdir(second_org.id, "inbox")

        manager.move_cross_org(org.id, "shared.txt", second_org.id, "inbox")

        dest_row = StorageFile.objects.get(org=second_org, path="inbox/shared.txt")
        assert dest_row.name == "shared.txt"
        assert not StorageFile.objects.filter(org=org, path="shared.txt").exists()
