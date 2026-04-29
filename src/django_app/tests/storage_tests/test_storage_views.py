from unittest.mock import MagicMock, patch

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework import status

from tables.models import Graph, GraphStorageFile, Organization, StorageFile
from tables.services.storage_service.dataclasses import (
    FileInfo,
    FileListItem,
    FileUploadResult,
    FolderInfo,
    TreeNode,
)


@pytest.fixture(autouse=True)
def mock_manager():
    """Patch get_storage_manager so every view instance uses our mock."""
    mgr = MagicMock()
    with patch("tables.views.storage_views.get_storage_manager", return_value=mgr):
        yield mgr


pytestmark = pytest.mark.django_db


class TestListFiles:
    def test_list_returns_items_from_manager(self, api_client, mock_manager):
        mock_manager.list_.return_value = [
            FileListItem(
                name="a.txt",
                type="file",
                size=10,
                modified="2024-01-01T00:00:00Z",
                is_empty=False,
            )
        ]

        resp = api_client.get("/api/storage/list/", {"path": ""})

        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.data["items"]) == 1
        assert resp.data["items"][0]["name"] == "a.txt"


class TestInfo:
    def test_info_returns_metadata_with_linked_graphs(self, api_client, mock_manager):
        mock_manager.info.return_value = FileInfo(
            name="f.txt",
            path="f.txt",
            size=5,
            content_type="text/plain",
            modified="2024-01-01T00:00:00Z",
        )

        resp = api_client.get("/api/storage/info/", {"path": "f.txt"})

        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["name"] == "f.txt"
        assert "graphs" in resp.data

    def test_info_returns_error_for_missing_file(self, api_client, mock_manager):
        mock_manager.info.side_effect = FileNotFoundError("gone")

        resp = api_client.get("/api/storage/info/", {"path": "ghost.txt"})

        assert resp.status_code == status.HTTP_404_NOT_FOUND


class TestDownload:
    def test_download_returns_octet_stream(self, api_client, mock_manager):
        mock_manager.download.return_value = b"file content"

        resp = api_client.get("/api/storage/download/", {"path": "f.txt"})

        assert resp.status_code == status.HTTP_200_OK
        assert resp["Content-Type"] == "application/octet-stream"
        assert resp.content == b"file content"

    def test_download_returns_error_for_missing_file(self, api_client, mock_manager):
        mock_manager.download.side_effect = FileNotFoundError("gone")

        resp = api_client.get("/api/storage/download/", {"path": "ghost.txt"})

        assert resp.status_code == status.HTTP_400_BAD_REQUEST


class TestUpload:
    def test_upload_returns_201_with_results(self, api_client, mock_manager):
        mock_manager.upload_file.return_value = FileUploadResult(
            type="file", path="notes.txt", size=5
        )
        uploaded_file = SimpleUploadedFile(
            "notes.txt", b"hello", content_type="text/plain"
        )

        resp = api_client.post("/api/storage/upload/", {"files": uploaded_file})

        assert resp.status_code == status.HTTP_201_CREATED, resp.data
        assert len(resp.data["uploaded"]) == 1

    def test_upload_converts_value_error_to_validation_error(
        self, api_client, mock_manager
    ):
        mock_manager.upload_file.side_effect = ValueError("password protected")
        uploaded_file = SimpleUploadedFile(
            "bad.zip", b"data", content_type="application/zip"
        )

        resp = api_client.post("/api/storage/upload/", {"files": uploaded_file})

        assert resp.status_code == status.HTTP_400_BAD_REQUEST


class TestRename:
    def test_rename_returns_success(self, api_client, mock_manager):
        resp = api_client.post(
            "/api/storage/rename/",
            {"from_path": "old.txt", "to_path": "new.txt"},
            format="json",
        )

        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["success"] is True

    def test_rename_returns_error_for_missing_source(self, api_client, mock_manager):
        mock_manager.rename.side_effect = FileNotFoundError("gone")

        resp = api_client.post(
            "/api/storage/rename/",
            {"from_path": "ghost.txt", "to_path": "new.txt"},
            format="json",
        )

        assert resp.status_code == status.HTTP_400_BAD_REQUEST


class TestMove:
    def test_move_dispatches_to_cross_org_when_org_ids_differ(
        self, api_client, mock_manager
    ):
        resp = api_client.post(
            "/api/storage/move/",
            {
                "from_path": "a.txt",
                "to_path": "b.txt",
                "source_org_id": 1,
                "destination_org_id": 2,
            },
            format="json",
        )

        assert resp.status_code == status.HTTP_200_OK
        mock_manager.move_cross_org.assert_called_once()
        mock_manager.move.assert_not_called()

    def test_move_dispatches_to_same_org_when_no_cross_org_ids(
        self, api_client, mock_manager
    ):
        resp = api_client.post(
            "/api/storage/move/",
            {"from_path": "a.txt", "to_path": "dest"},
            format="json",
        )

        assert resp.status_code == status.HTTP_200_OK
        mock_manager.move.assert_called_once()
        mock_manager.move_cross_org.assert_not_called()


class TestCopy:
    def test_copy_dispatches_to_cross_org_when_org_ids_differ(
        self, api_client, mock_manager
    ):
        resp = api_client.post(
            "/api/storage/copy/",
            {
                "from_path": "a.txt",
                "to_path": "b.txt",
                "source_org_id": 1,
                "destination_org_id": 2,
            },
            format="json",
        )

        assert resp.status_code == status.HTTP_200_OK
        mock_manager.copy_cross_org.assert_called_once()

    def test_copy_dispatches_to_same_org_when_no_cross_org_ids(
        self, api_client, mock_manager
    ):
        resp = api_client.post(
            "/api/storage/copy/",
            {"from_path": "a.txt", "to_path": "dest"},
            format="json",
        )

        assert resp.status_code == status.HTTP_200_OK
        mock_manager.copy.assert_called_once()
        mock_manager.copy_cross_org.assert_not_called()


class TestDelete:
    def test_delete_returns_204(self, api_client, mock_manager):
        resp = api_client.delete(
            "/api/storage/delete/", {"paths": ["a.txt"]}, format="json"
        )

        assert resp.status_code == status.HTTP_204_NO_CONTENT


class TestMkdir:
    def test_mkdir_returns_201(self, api_client, mock_manager):
        mock_manager.info.side_effect = FileNotFoundError("not found")

        resp = api_client.post(
            "/api/storage/mkdir/", {"path": "new_folder"}, format="json"
        )

        assert resp.status_code == status.HTTP_201_CREATED


class TestAddToGraph:
    def test_add_to_graph_creates_link_and_appends_slash_for_folders(
        self, api_client, mock_manager
    ):
        graph = Graph.objects.create(name="test-graph")
        mock_manager.info.return_value = FolderInfo(
            name="docs", path="docs/", modified="2024-01-01T00:00:00Z"
        )

        resp = api_client.post(
            "/api/storage/add-to-graph/",
            {"paths": ["docs"], "graph_ids": [graph.id]},
            format="json",
        )

        assert resp.status_code == status.HTTP_201_CREATED
        storage_file = StorageFile.objects.get(path="docs/")
        assert GraphStorageFile.objects.filter(
            graph=graph, storage_file=storage_file
        ).exists()


class TestRemoveFromGraph:
    def test_remove_from_graph_deletes_records(self, api_client, mock_manager):
        # Trigger _resolve_context to create the default org so we can look it up
        mock_manager.list_.return_value = []
        api_client.get("/api/storage/list/", {"path": ""})

        org = Organization.objects.get(name="default")
        graph = Graph.objects.create(name="test-graph")
        storage_file = StorageFile.objects.create(org=org, path="file.txt")
        GraphStorageFile.objects.create(graph=graph, storage_file=storage_file)

        resp = api_client.delete(
            "/api/storage/remove-from-graph/",
            {"paths": ["file.txt"], "graph_ids": [graph.id]},
            format="json",
        )

        assert resp.status_code == status.HTTP_204_NO_CONTENT
        assert not GraphStorageFile.objects.filter(
            graph=graph, storage_file=storage_file
        ).exists()


class TestGraphFiles:
    def test_graph_files_returns_files_for_graph(self, api_client, mock_manager):
        # Trigger _resolve_context to create the default org
        mock_manager.list_.return_value = []
        api_client.get("/api/storage/list/", {"path": ""})

        org = Organization.objects.get(name="default")
        graph = Graph.objects.create(name="test-graph")
        storage_file = StorageFile.objects.create(org=org, path="attached.txt")
        GraphStorageFile.objects.create(graph=graph, storage_file=storage_file)

        resp = api_client.get("/api/storage/graph-files/", {"graph_id": graph.id})

        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.data) == 1
        assert resp.data[0]["path"] == "attached.txt"


class TestTree:
    def test_tree_returns_nested_structure(self, api_client, mock_manager):
        root = TreeNode(
            name="reports",
            path="reports/",
            type="folder",
            size=0,
            modified=None,
            children=[
                TreeNode(
                    name="q1.pdf",
                    path="reports/q1.pdf",
                    type="file",
                    size=10,
                    modified="2024-01-01T00:00:00Z",
                    children=None,
                ),
            ],
        )
        mock_manager.info.return_value = FolderInfo(
            name="reports",
            path="reports/",
            modified="2024-01-01T00:00:00Z",
        )
        mock_manager.list_tree.return_value = (root, False)

        resp = api_client.get("/api/storage/tree/", {"path": "reports"})

        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["truncated"] is False
        assert resp.data["tree"]["name"] == "reports"
        assert resp.data["tree"]["children"][0]["name"] == "q1.pdf"
        assert resp.data["tree"]["children"][0]["children"] is None

    def test_tree_forwards_max_depth_to_manager(self, api_client, mock_manager):
        mock_manager.info.return_value = FolderInfo(
            name="", path="", modified="2024-01-01T00:00:00Z"
        )
        mock_manager.list_tree.return_value = (
            TreeNode(
                name="", path="", type="folder", size=0, modified=None, children=[]
            ),
            False,
        )
        api_client.get("/api/storage/tree/", {"path": "x", "max_depth": 2})
        assert mock_manager.list_tree.call_args.kwargs["max_depth"] == 2

    def test_tree_surfaces_truncated_flag(self, api_client, mock_manager):
        mock_manager.info.return_value = FolderInfo(
            name="", path="", modified="2024-01-01T00:00:00Z"
        )
        mock_manager.list_tree.return_value = (
            TreeNode(
                name="", path="", type="folder", size=0, modified=None, children=[]
            ),
            True,
        )
        resp = api_client.get("/api/storage/tree/", {"path": "big"})
        assert resp.data["truncated"] is True

    def test_tree_returns_404_for_missing_path(self, api_client, mock_manager):
        mock_manager.info.side_effect = FileNotFoundError("gone")
        resp = api_client.get("/api/storage/tree/", {"path": "nope"})
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def test_tree_rejects_file_path_with_400(self, api_client, mock_manager):
        mock_manager.info.return_value = FileInfo(
            name="f.txt",
            path="f.txt",
            size=1,
            content_type="text/plain",
            modified="2024-01-01T00:00:00Z",
        )
        resp = api_client.get("/api/storage/tree/", {"path": "f.txt"})
        assert resp.status_code == status.HTTP_400_BAD_REQUEST


class TestSearch:
    def test_search_returns_paged_results(self, api_client, mock_manager):
        mock_manager.search.return_value = (
            [
                {"path": "reports/q1_report.pdf", "name": "q1_report.pdf"},
                {"path": "archive/old_report.txt", "name": "old_report.txt"},
            ],
            137,
        )
        resp = api_client.get("/api/storage/search/", {"q": "report"})
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["total"] == 137
        assert resp.data["offset"] == 0
        assert resp.data["limit"] == 50
        assert len(resp.data["results"]) == 2

    def test_search_forwards_path_limit_offset(self, api_client, mock_manager):
        mock_manager.search.return_value = ([], 0)
        api_client.get(
            "/api/storage/search/",
            {
                "q": "rep",
                "path": "reports/",
                "limit": 10,
                "offset": 20,
            },
        )
        kwargs = mock_manager.search.call_args.kwargs
        assert kwargs["q"] == "rep"
        assert kwargs["path"] == "reports"
        assert kwargs["limit"] == 10
        assert kwargs["offset"] == 20

    def test_search_rejects_short_query(self, api_client, mock_manager):
        resp = api_client.get("/api/storage/search/", {"q": "r"})
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_search_requires_q_parameter(self, api_client, mock_manager):
        resp = api_client.get("/api/storage/search/")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_search_rejects_limit_over_max(self, api_client, mock_manager):
        resp = api_client.get("/api/storage/search/", {"q": "rep", "limit": 999})
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
