import tarfile
import zipfile
from io import BytesIO

import pytest
from rest_framework.exceptions import PermissionDenied

from tables.models import StorageFile
from tables.services.storage_service.dataclasses import (
    ArchiveUploadResult,
    FileInfo,
    FolderInfo,
    FileUploadResult,
    TreeNode,
    UploadResult,
)
from tables.services.storage_service.manager import StorageManager


@pytest.fixture(autouse=True)
def patch_sync(mocker):
    """Isolate manager from DB sync — sync has its own tests."""
    return mocker.patch("tables.services.storage_service.manager.StorageFileSync")


# --- Path helpers (no DB needed) ---


class TestPathHelpers:
    def test_build_storage_key_prepends_org_prefix(self, storage_manager):
        assert storage_manager._build_storage_key(5, "docs/a.txt") == "org_5/docs/a.txt"

    def test_build_storage_key_strips_leading_slash(self, storage_manager):
        assert storage_manager._build_storage_key(1, "/a.txt") == "org_1/a.txt"

    def test_strip_org_prefix_removes_matching_prefix(self, storage_manager):
        assert storage_manager._strip_org_prefix(1, "org_1/a.txt") == "a.txt"

    def test_strip_org_prefix_passthrough_when_no_match(self, storage_manager):
        assert storage_manager._strip_org_prefix(1, "other/a.txt") == "other/a.txt"


# --- Permission gate ---


@pytest.mark.django_db
class TestPermission:
    def test_require_permission_passes_for_org_member(
        self, storage_manager, org, org_user
    ):
        from tables.services.storage_service.enums import StorageAction

        # Should not raise
        storage_manager._require_permission("testuser", org.id, StorageAction.LIST, "")

    def test_require_permission_raises_for_non_member(self, storage_manager, org):
        from tables.services.storage_service.enums import StorageAction

        with pytest.raises(PermissionDenied):
            storage_manager._require_permission(
                "nobody", org.id, StorageAction.LIST, ""
            )


# --- Delegation + sync ---


@pytest.mark.django_db
class TestDelegation:
    def test_upload_delegates_to_backend_with_org_key_and_syncs(
        self, storage_manager, mock_backend, org, org_user, patch_sync
    ):
        mock_backend.upload.return_value = UploadResult(
            path="org_{}/docs/f.txt".format(org.id), size=10
        )
        result = storage_manager.upload(
            "testuser", org.id, "docs/f.txt", BytesIO(b"data")
        )
        args = mock_backend.upload.call_args[0]
        assert args[0] == f"org_{org.id}/docs/f.txt"
        assert result.path == "docs/f.txt"
        patch_sync.on_upload.assert_called_once_with(org.id, "docs/f.txt", size=10)

    def test_delete_delegates_to_backend_and_syncs(
        self, storage_manager, mock_backend, org, org_user, patch_sync
    ):
        storage_manager.delete("testuser", org.id, "old.txt")
        mock_backend.delete.assert_called_once_with(f"org_{org.id}/old.txt")
        patch_sync.on_delete.assert_called_once_with(org.id, "old.txt")

    def test_move_builds_both_org_keys_and_syncs(
        self, storage_manager, mock_backend, org, org_user, patch_sync
    ):
        storage_manager.move("testuser", org.id, "a.txt", "dest")
        mock_backend.move.assert_called_once_with(
            f"org_{org.id}/a.txt", f"org_{org.id}/dest"
        )
        patch_sync.on_move.assert_called_once_with(org.id, "a.txt", "dest")

    def test_rename_delegates_and_syncs_via_on_move(
        self, storage_manager, mock_backend, org, org_user, patch_sync
    ):
        storage_manager.rename("testuser", org.id, "old.txt", "new.txt")
        mock_backend.rename.assert_called_once_with(
            f"org_{org.id}/old.txt", f"org_{org.id}/new.txt"
        )
        patch_sync.on_move.assert_called_once_with(org.id, "old.txt", "new.txt")

    def test_copy_strips_org_prefix_from_returned_keys_and_syncs(
        self, storage_manager, mock_backend, org, org_user, patch_sync
    ):
        mock_backend.copy.return_value = [
            f"org_{org.id}/dest/a.txt",
            f"org_{org.id}/dest/b.txt",
        ]
        storage_manager.copy("testuser", org.id, "src", "dest")
        patch_sync.on_copy.assert_called_once_with(org.id, ["dest/a.txt", "dest/b.txt"])

    def test_info_strips_org_prefix_from_result_path(
        self, storage_manager, org, org_user
    ):
        StorageFile.objects.create(
            org=org,
            path="docs/f.txt",
            name="f.txt",
            item_type="file",
            parent_path="docs/",
            size=5,
        )
        result = storage_manager.info("testuser", org.id, "docs/f.txt")
        assert isinstance(result, FileInfo)
        assert result.path == "docs/f.txt"

    def test_decorated_method_raises_permission_denied_for_non_member(
        self, storage_manager, org
    ):
        with pytest.raises(PermissionDenied):
            storage_manager.list_("nobody", org.id, "")


# --- _is_archive ---


class TestIsArchive:
    def test_is_archive_true_for_zip(self):
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("a.txt", "data")
        buf.seek(0)
        assert StorageManager._is_archive(buf, "archive.zip") is True

    def test_is_archive_true_for_tar(self):
        buf = BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tf:
            info = tarfile.TarInfo("a.txt")
            info.size = 4
            tf.addfile(info, BytesIO(b"data"))
        buf.seek(0)
        assert StorageManager._is_archive(buf, "archive.tar") is True

    def test_is_archive_false_for_docx(self):
        # .docx is actually a ZIP but should NOT be treated as archive
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("[Content_Types].xml", "<Types/>")
        buf.seek(0)
        assert StorageManager._is_archive(buf, "document.docx") is False

    def test_is_archive_false_for_xlsx(self):
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("sheet.xml", "<data/>")
        buf.seek(0)
        assert StorageManager._is_archive(buf, "spreadsheet.xlsx") is False

    def test_is_archive_false_for_plain_text(self):
        buf = BytesIO(b"just plain text")
        assert StorageManager._is_archive(buf, "readme.txt") is False


# --- upload_file dispatch ---


@pytest.mark.django_db
class TestUploadFile:
    def test_upload_file_extracts_archive_when_detected(
        self, storage_manager, mock_backend, org, org_user, patch_sync
    ):
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("inner.txt", "content")
        buf.seek(0)
        buf.name = "bundle.zip"

        mock_backend.upload_archive.return_value = [f"org_{org.id}/inner.txt"]
        result = storage_manager.upload_file("testuser", org.id, "", buf)
        assert isinstance(result, ArchiveUploadResult)
        mock_backend.upload_archive.assert_called_once()

    def test_upload_file_stores_regular_file_when_not_archive(
        self, storage_manager, mock_backend, org, org_user, patch_sync
    ):
        buf = BytesIO(b"plain content")
        buf.name = "notes.txt"
        mock_backend.upload.return_value = UploadResult(
            path=f"org_{org.id}/notes.txt", size=13
        )
        result = storage_manager.upload_file("testuser", org.id, "", buf)
        assert isinstance(result, FileUploadResult)
        assert result.path == "notes.txt"


# --- Cross-org ---


@pytest.mark.django_db
class TestCrossOrg:
    def test_copy_cross_org_checks_both_orgs(
        self,
        storage_manager,
        mock_backend,
        org,
        org_user,
        second_org,
        second_org_user,
        patch_sync,
    ):
        mock_backend.copy.return_value = [f"org_{second_org.id}/dest.txt"]
        storage_manager.copy_cross_org(
            "testuser", org.id, "src.txt", second_org.id, "dest.txt"
        )
        mock_backend.copy.assert_called_once()
        patch_sync.on_copy_cross_org.assert_called_once()

    def test_copy_cross_org_raises_when_missing_source_membership(
        self, storage_manager, org, second_org, second_org_user
    ):
        # "testuser" is NOT a member of org (no org_user fixture)
        with pytest.raises(PermissionDenied):
            storage_manager.copy_cross_org(
                "testuser", org.id, "src.txt", second_org.id, "dest.txt"
            )

    def test_copy_cross_org_raises_when_missing_dest_membership(
        self, storage_manager, org, org_user, second_org
    ):
        # "testuser" is NOT a member of second_org (no second_org_user fixture)
        with pytest.raises(PermissionDenied):
            storage_manager.copy_cross_org(
                "testuser", org.id, "src.txt", second_org.id, "dest.txt"
            )

    def test_move_cross_org_checks_delete_source_upload_dest(
        self,
        storage_manager,
        mock_backend,
        org,
        org_user,
        second_org,
        second_org_user,
        patch_sync,
    ):
        storage_manager.move_cross_org(
            "testuser", org.id, "src.txt", second_org.id, "dest.txt"
        )
        mock_backend.move.assert_called_once_with(
            f"org_{org.id}/src.txt", f"org_{second_org.id}/dest.txt"
        )
        patch_sync.on_move_cross_org.assert_called_once()


@pytest.mark.django_db
class TestListTreeManager:
    @pytest.fixture
    def db_manager(self, local_backend, org, org_user):
        """Manager backed by a LocalStorageBackend (no mock) with DB rows seeded."""
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

        return StorageManager(local_backend)

    def test_list_tree_builds_tree_from_db_rows(self, db_manager, org, org_user):
        root, truncated = db_manager.list_tree("testuser", org.id, "reports")
        assert root.path == "reports/"
        assert root.children[0].path == "reports/q1.pdf"
        assert truncated is False

    def test_list_tree_respects_permission_gate(
        self, storage_manager, mock_backend, org
    ):
        with pytest.raises(PermissionDenied):
            storage_manager.list_tree("nobody", org.id, "")


@pytest.mark.django_db
class TestListManager:
    @pytest.fixture
    def db_manager(self, local_backend, org, org_user):
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
        return StorageManager(local_backend)

    def test_list_root_returns_folder_and_file(self, db_manager, org, org_user):
        items = db_manager.list_("testuser", org.id, "")
        names = {i.name for i in items}
        assert "docs" in names
        assert "root.txt" in names

    def test_folder_is_not_empty_when_it_has_children(self, db_manager, org, org_user):
        items = db_manager.list_("testuser", org.id, "")
        docs = next(i for i in items if i.name == "docs")
        assert docs.is_empty is False

    def test_file_is_empty_false(self, db_manager, org, org_user):
        items = db_manager.list_("testuser", org.id, "")
        txt = next(i for i in items if i.name == "root.txt")
        assert txt.is_empty is False
        assert txt.size == 42

    def test_folder_modified_is_none_when_s3_modified_null(
        self, db_manager, org, org_user
    ):
        items = db_manager.list_("testuser", org.id, "")
        docs = next(i for i in items if i.name == "docs")
        assert docs.modified is None

    def test_list_with_prefix_returns_only_direct_children(
        self, db_manager, org, org_user
    ):
        items = db_manager.list_("testuser", org.id, "docs")
        assert len(items) == 1
        assert items[0].name == "inner.txt"


@pytest.mark.django_db
class TestInfoManager:
    @pytest.fixture
    def db_manager(self, local_backend, org, org_user):
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
        return StorageManager(local_backend)

    def test_info_returns_file_info_for_file_path(self, db_manager, org, org_user):
        result = db_manager.info("testuser", org.id, "docs/note.txt")
        assert isinstance(result, FileInfo)
        assert result.name == "note.txt"
        assert result.size == 99

    def test_info_returns_folder_info_for_folder_path(self, db_manager, org, org_user):
        result = db_manager.info("testuser", org.id, "docs")
        assert isinstance(result, FolderInfo)
        assert result.path == "docs/"

    def test_info_raises_for_missing_path(self, db_manager, org, org_user):
        with pytest.raises(FileNotFoundError):
            db_manager.info("testuser", org.id, "nonexistent.txt")


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
        results, total = storage_manager.search("testuser", org.id, q="report")
        assert total == 3
        names = [r["name"] for r in results]
        assert "q1_report.pdf" in names
        assert "note.txt" not in names

    def test_search_is_case_insensitive(self, storage_manager, org, org_user, seeded):
        _, total = storage_manager.search("testuser", org.id, q="REPORT")
        assert total == 3

    def test_search_scoped_to_path(self, storage_manager, org, org_user, seeded):
        _, total = storage_manager.search(
            "testuser", org.id, q="report", path="reports/"
        )
        assert total == 2

    def test_search_excludes_other_orgs(
        self, storage_manager, org, second_org, org_user, seeded
    ):
        _, total = storage_manager.search("testuser", org.id, q="q1_report")
        assert total == 1

    def test_search_excludes_folder_rows(self, storage_manager, org, org_user, seeded):
        results, total = storage_manager.search("testuser", org.id, q="reports")
        names = [r["name"] for r in results]
        assert "reports" not in names

    def test_search_pagination(self, storage_manager, org, org_user, seeded):
        page1, total = storage_manager.search(
            "testuser", org.id, q="report", limit=2, offset=0
        )
        page2, _ = storage_manager.search(
            "testuser", org.id, q="report", limit=2, offset=2
        )
        assert len(page1) == 2
        assert len(page2) == 1
        assert total == 3
        assert page1[0]["path"] != page2[0]["path"]

    def test_search_results_include_id(self, storage_manager, org, org_user, seeded):
        results, _ = storage_manager.search("testuser", org.id, q="q1_report")
        assert len(results) == 1
        row = StorageFile.objects.get(org=org, path="reports/q1_report.pdf")
        assert results[0]["id"] == row.id


@pytest.mark.django_db
class TestStorageIdExposure:
    """Verify that list_(), info(), list_tree() carry the DB row id through."""

    @pytest.fixture
    def db_manager(self, local_backend, org, org_user):
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

        return StorageManager(local_backend)

    def test_list_file_item_carries_row_id(self, db_manager, org, org_user):
        items = db_manager.list_("testuser", org.id, "docs")
        file_item = next(i for i in items if i.name == "note.txt")
        expected_id = StorageFile.objects.get(org=org, path="docs/note.txt").id
        assert file_item.id == expected_id

    def test_list_folder_item_carries_row_id(self, db_manager, org, org_user):
        items = db_manager.list_("testuser", org.id, "")
        folder_item = next(i for i in items if i.name == "docs")
        expected_id = StorageFile.objects.get(org=org, path="docs/").id
        assert folder_item.id == expected_id

    def test_info_file_carries_row_id(self, db_manager, org, org_user):
        result = db_manager.info("testuser", org.id, "docs/note.txt")
        expected_id = StorageFile.objects.get(org=org, path="docs/note.txt").id
        assert result.id == expected_id

    def test_info_folder_carries_row_id(self, db_manager, org, org_user):
        result = db_manager.info("testuser", org.id, "docs")
        expected_id = StorageFile.objects.get(org=org, path="docs/").id
        assert result.id == expected_id

    def test_list_tree_leaf_file_carries_row_id(self, db_manager, org, org_user):
        root, _ = db_manager.list_tree("testuser", org.id, "docs")
        leaf = next(child for child in root.children if child.name == "note.txt")
        expected_id = StorageFile.objects.get(org=org, path="docs/note.txt").id
        assert leaf.id == expected_id

    def test_list_tree_leaf_folder_carries_row_id(self, db_manager, org, org_user):
        root, _ = db_manager.list_tree("testuser", org.id, "")
        folder_node = next(child for child in root.children if child.name == "docs")
        expected_id = StorageFile.objects.get(org=org, path="docs/").id
        assert folder_node.id == expected_id

    def test_list_tree_root_node_id_is_none(self, db_manager, org, org_user):
        root, _ = db_manager.list_tree("testuser", org.id, "docs")
        assert root.id is None
