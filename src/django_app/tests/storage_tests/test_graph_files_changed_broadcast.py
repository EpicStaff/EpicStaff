"""broadcast graph_files_changed to a graph's collaboration group
whenever its attached-files list changes.

Covers the two graph-scoped storage-view hook sites (add-to-graph,
remove-from-graph) — these stay per-graph (see manager.py hooks, which
switched to org-wide broadcasts instead). Uses the real channel layer
(configured in settings, same as tests/graph_collab/test_notifications.py)
with async_to_sync to receive messages synchronously from these sync
APIClient-driven tests.
"""

import asyncio
from unittest.mock import MagicMock, patch

import pytest
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from rest_framework import status

from tables.models import Graph, GraphStorageFile, StorageFile
from tables.services.storage_service.dataclasses import FileInfo, FolderInfo


@pytest.fixture(autouse=True)
def mock_manager():
    """Patch get_storage_manager so every view instance uses our mock."""
    mgr = MagicMock()
    with patch("tables.views.storage_views.get_storage_manager", return_value=mgr):
        yield mgr


pytestmark = pytest.mark.django_db


def _subscribe(group_name: str) -> tuple:
    channel_layer = get_channel_layer()
    channel_name = async_to_sync(channel_layer.new_channel)()
    async_to_sync(channel_layer.group_add)(group_name, channel_name)
    return channel_layer, channel_name


def _receive(channel_layer, channel_name) -> dict:
    return async_to_sync(channel_layer.receive)(channel_name)


def _assert_nothing_received(channel_layer, channel_name, timeout: float = 0.3) -> None:
    async def _inner():
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(channel_layer.receive(channel_name), timeout=timeout)

    async_to_sync(_inner)()


def _file_info(path: str) -> FileInfo:
    return FileInfo(
        name=path,
        path=path,
        size=5,
        content_type="text/plain",
        modified="2024-01-01T00:00:00Z",
    )


class TestAddToGraphBroadcast:
    def test_emits_event_for_each_targeted_graph(
        self, superadmin_auth_client, default_org, mock_manager
    ):
        graph_a = Graph.objects.create(name="graph-a", org=default_org)
        graph_b = Graph.objects.create(name="graph-b", org=default_org)
        mock_manager.info.return_value = _file_info("shared.txt")

        channel_a, name_a = _subscribe(f"graph_edit_{graph_a.id}")
        channel_b, name_b = _subscribe(f"graph_edit_{graph_b.id}")

        resp = superadmin_auth_client.post(
            "/api/storage/add-to-graph/",
            {"paths": ["shared.txt"], "graph_ids": [graph_a.id, graph_b.id]},
            format="json",
        )

        assert resp.status_code == status.HTTP_201_CREATED

        message_a = _receive(channel_a, name_a)
        message_b = _receive(channel_b, name_b)

        assert message_a["type"] == "graph_files_changed"
        assert message_a["graph_id"] == graph_a.id
        assert message_b["type"] == "graph_files_changed"
        assert message_b["graph_id"] == graph_b.id

    def test_dedupes_repeated_graph_id_across_multiple_paths(
        self, superadmin_auth_client, default_org, mock_manager
    ):
        graph = Graph.objects.create(name="graph", org=default_org)
        mock_manager.info.return_value = _file_info("a.txt")

        channel_layer, channel_name = _subscribe(f"graph_edit_{graph.id}")

        resp = superadmin_auth_client.post(
            "/api/storage/add-to-graph/",
            {"paths": ["a.txt", "b.txt"], "graph_ids": [graph.id]},
            format="json",
        )

        assert resp.status_code == status.HTTP_201_CREATED
        _receive(channel_layer, channel_name)
        _assert_nothing_received(channel_layer, channel_name)


class TestRemoveFromGraphBroadcast:
    def test_emits_only_for_graphs_with_removed_rows(
        self, superadmin_auth_client, default_org, mock_manager
    ):
        graph_a = Graph.objects.create(name="graph-a", org=default_org)
        graph_b = Graph.objects.create(name="graph-b", org=default_org)
        storage_file = StorageFile.objects.create(org=default_org, path="file.txt")
        GraphStorageFile.objects.create(graph=graph_a, storage_file=storage_file)

        channel_a, name_a = _subscribe(f"graph_edit_{graph_a.id}")
        channel_b, name_b = _subscribe(f"graph_edit_{graph_b.id}")

        resp = superadmin_auth_client.delete(
            "/api/storage/remove-from-graph/",
            {"paths": ["file.txt"], "graph_ids": [graph_a.id, graph_b.id]},
            format="json",
        )

        assert resp.status_code == status.HTTP_204_NO_CONTENT
        message_a = _receive(channel_a, name_a)
        assert message_a["type"] == "graph_files_changed"
        assert message_a["graph_id"] == graph_a.id
        _assert_nothing_received(channel_b, name_b)

    def test_removes_attached_folder_path_and_emits_event(
        self, superadmin_auth_client, default_org, mock_manager
    ):
        """The attached folder itself (stored with a trailing slash by
        add_to_graph) is what gets matched and removed here — not every file
        underneath it. remove_from_graph builds ``normalized_paths`` as
        ``{p, p.rstrip("/"), p.rstrip("/") + "/"}``, so requesting removal of
        "docs" (no trailing slash) still matches the "docs/" row that
        add_to_graph created."""
        graph = Graph.objects.create(name="graph", org=default_org)
        mock_manager.info.return_value = FolderInfo(
            name="docs", path="docs/", modified="2024-01-01T00:00:00Z"
        )

        add_resp = superadmin_auth_client.post(
            "/api/storage/add-to-graph/",
            {"paths": ["docs"], "graph_ids": [graph.id]},
            format="json",
        )
        assert add_resp.status_code == status.HTTP_201_CREATED
        assert GraphStorageFile.objects.filter(
            graph=graph, storage_file__path="docs/"
        ).exists()

        channel_layer, channel_name = _subscribe(f"graph_edit_{graph.id}")

        remove_resp = superadmin_auth_client.delete(
            "/api/storage/remove-from-graph/",
            {"paths": ["docs"], "graph_ids": [graph.id]},
            format="json",
        )

        assert remove_resp.status_code == status.HTTP_204_NO_CONTENT
        assert not GraphStorageFile.objects.filter(
            graph=graph, storage_file__path="docs/"
        ).exists()

        message = _receive(channel_layer, channel_name)
        assert message["type"] == "graph_files_changed"
        assert message["graph_id"] == graph.id

    def test_no_matching_rows_emits_nothing(
        self, superadmin_auth_client, default_org, mock_manager
    ):
        graph = Graph.objects.create(name="graph", org=default_org)

        channel_layer, channel_name = _subscribe(f"graph_edit_{graph.id}")

        resp = superadmin_auth_client.delete(
            "/api/storage/remove-from-graph/",
            {"paths": ["nothing-here.txt"], "graph_ids": [graph.id]},
            format="json",
        )

        assert resp.status_code == status.HTTP_204_NO_CONTENT
        _assert_nothing_received(channel_layer, channel_name)
