"""StorageManager must broadcast graph_files_changed to the
org-wide ``org_{org_id}`` group for every storage-tree mutation — upload,
upload_file (file + archive), mkdir, delete, move, rename, copy,
copy_cross_org, move_cross_org.

The broadcast is unconditional (it does not depend on any file being
attached to a graph), which is the whole point: it's how mutations on
files attached to NO graph reach an open "Add files" dialog. These tests
mock ``StorageFileSync`` (its own tests cover the DB-sync behaviour) so
each case only has to assert the manager's notify call.
"""

from io import BytesIO

import pytest
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from tables.services.storage_service.dataclasses import UploadResult


pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def patch_sync(mocker):
    """Isolate the manager from DB sync — sync has its own tests."""
    return mocker.patch("tables.services.storage_service.manager.StorageFileSync")


def _subscribe(org_id: int) -> tuple:
    channel_layer = get_channel_layer()
    channel_name = async_to_sync(channel_layer.new_channel)()
    async_to_sync(channel_layer.group_add)(f"org_{org_id}", channel_name)
    return channel_layer, channel_name


def _receive(channel_layer, channel_name) -> dict:
    return async_to_sync(channel_layer.receive)(channel_name)


class TestUploadBroadcast:
    def test_upload_emits_org_event(self, storage_manager, mock_backend, org, org_user):
        mock_backend.upload.return_value = UploadResult(
            path=f"org_{org.id}/a.txt", size=4
        )
        channel_layer, channel_name = _subscribe(org.id)

        storage_manager.upload(org.id, "a.txt", BytesIO(b"data"))

        message = _receive(channel_layer, channel_name)
        assert message["type"] == "graph_files_changed"
        assert message["graph_id"] is None

    def test_upload_file_regular_emits_org_event(
        self, storage_manager, mock_backend, org, org_user
    ):
        mock_backend.upload.return_value = UploadResult(
            path=f"org_{org.id}/notes.txt", size=13
        )
        channel_layer, channel_name = _subscribe(org.id)

        buf = BytesIO(b"plain content")
        buf.name = "notes.txt"
        storage_manager.upload_file(org.id, "", buf)

        message = _receive(channel_layer, channel_name)
        assert message["type"] == "graph_files_changed"
        assert message["graph_id"] is None

    def test_upload_file_archive_emits_org_event(
        self, storage_manager, mock_backend, org, org_user, sample_zip
    ):
        mock_backend.upload_archive.return_value = [f"org_{org.id}/hello.txt"]
        channel_layer, channel_name = _subscribe(org.id)

        storage_manager.upload_file(org.id, "", sample_zip)

        message = _receive(channel_layer, channel_name)
        assert message["type"] == "graph_files_changed"
        assert message["graph_id"] is None


class TestMkdirBroadcast:
    def test_mkdir_emits_org_event(self, storage_manager, mock_backend, org, org_user):
        channel_layer, channel_name = _subscribe(org.id)

        storage_manager.mkdir(org.id, "new-folder")

        message = _receive(channel_layer, channel_name)
        assert message["type"] == "graph_files_changed"
        assert message["graph_id"] is None


class TestDeleteBroadcast:
    def test_delete_emits_org_event_for_file_attached_to_no_graph(
        self, storage_manager, mock_backend, org, org_user
    ):
        """The whole point: a mutation on a file with zero graph attachments
        still reaches the org group."""
        channel_layer, channel_name = _subscribe(org.id)

        storage_manager.delete(org.id, "unattached.txt")

        message = _receive(channel_layer, channel_name)
        assert message["type"] == "graph_files_changed"
        assert message["graph_id"] is None


class TestMoveRenameBroadcast:
    def test_move_emits_org_event(self, storage_manager, mock_backend, org, org_user):
        channel_layer, channel_name = _subscribe(org.id)

        storage_manager.move(org.id, "a.txt", "dest.txt")

        message = _receive(channel_layer, channel_name)
        assert message["type"] == "graph_files_changed"
        assert message["graph_id"] is None

    def test_rename_emits_org_event(self, storage_manager, mock_backend, org, org_user):
        channel_layer, channel_name = _subscribe(org.id)

        storage_manager.rename(org.id, "old.txt", "new.txt")

        message = _receive(channel_layer, channel_name)
        assert message["type"] == "graph_files_changed"
        assert message["graph_id"] is None


class TestCopyBroadcast:
    def test_copy_emits_org_event(self, storage_manager, mock_backend, org, org_user):
        mock_backend.copy.return_value = [f"org_{org.id}/dest.txt"]
        channel_layer, channel_name = _subscribe(org.id)

        storage_manager.copy(org.id, "src.txt", "dest.txt")

        message = _receive(channel_layer, channel_name)
        assert message["type"] == "graph_files_changed"
        assert message["graph_id"] is None


class TestCrossOrgBroadcast:
    def test_copy_cross_org_emits_event_only_to_destination_org(
        self, storage_manager, mock_backend, org, org_user, second_org, second_org_user
    ):
        mock_backend.copy.return_value = [f"org_{second_org.id}/dest.txt"]
        src_channel, src_name = _subscribe(org.id)
        dst_channel, dst_name = _subscribe(second_org.id)

        storage_manager.copy_cross_org(org.id, "src.txt", second_org.id, "dest.txt")

        message = _receive(dst_channel, dst_name)
        assert message["type"] == "graph_files_changed"

        async def _assert_src_silent():
            import asyncio

            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(src_channel.receive(src_name), timeout=0.3)

        async_to_sync(_assert_src_silent)()

    def test_move_cross_org_emits_events_to_both_orgs(
        self, storage_manager, mock_backend, org, org_user, second_org, second_org_user
    ):
        src_channel, src_name = _subscribe(org.id)
        dst_channel, dst_name = _subscribe(second_org.id)

        storage_manager.move_cross_org(org.id, "src.txt", second_org.id, "dest.txt")

        src_message = _receive(src_channel, src_name)
        dst_message = _receive(dst_channel, dst_name)
        assert src_message["type"] == "graph_files_changed"
        assert dst_message["type"] == "graph_files_changed"
