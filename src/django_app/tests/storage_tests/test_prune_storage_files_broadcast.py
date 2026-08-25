"""`prune_storage_files` must broadcast graph_files_changed to the
org-wide ``org_{org_id}`` group once per org that had orphans pruned — but
only on real deletes, never under --dry-run. This covers files pruned with
no graph attachment at all, since the org broadcast no longer depends on
GraphStorageFile rows.
"""

import asyncio
from unittest.mock import MagicMock, patch

import pytest
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.core.management import call_command

from tables.models import StorageFile


pytestmark = pytest.mark.django_db


def _subscribe(org_id: int) -> tuple:
    channel_layer = get_channel_layer()
    channel_name = async_to_sync(channel_layer.new_channel)()
    async_to_sync(channel_layer.group_add)(f"org_{org_id}", channel_name)
    return channel_layer, channel_name


def _receive(channel_layer, channel_name) -> dict:
    return async_to_sync(channel_layer.receive)(channel_name)


def _assert_nothing_received(channel_layer, channel_name, timeout: float = 0.3) -> None:
    async def _inner():
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(channel_layer.receive(channel_name), timeout=timeout)

    async_to_sync(_inner)()


@pytest.fixture(autouse=True)
def mock_storage_manager_backend():
    """The command lists real backend keys to find orphans — mock the
    backend so no S3/local filesystem is required; empty key list makes
    every DB StorageFile row an orphan."""
    mgr = MagicMock()
    mgr._backend.list_all_keys.return_value = []
    with patch("tables.services.storage_service.get_storage_manager", return_value=mgr):
        yield mgr


class TestPruneBroadcast:
    def test_prune_emits_org_event_for_orphan_attached_to_no_graph(self, org):
        StorageFile.objects.create(org=org, path="orphan.txt")
        channel_layer, channel_name = _subscribe(org.id)

        call_command("prune_storage_files", f"--org-id={org.id}")

        message = _receive(channel_layer, channel_name)
        assert message["type"] == "graph_files_changed"
        assert message["graph_id"] is None

    def test_prune_emits_single_org_event_regardless_of_orphan_count(self, org):
        StorageFile.objects.create(org=org, path="orphan-1.txt")
        StorageFile.objects.create(org=org, path="orphan-2.txt")
        channel_layer, channel_name = _subscribe(org.id)

        call_command("prune_storage_files", f"--org-id={org.id}")

        _receive(channel_layer, channel_name)
        _assert_nothing_received(channel_layer, channel_name)

    def test_prune_dry_run_emits_nothing(self, org):
        StorageFile.objects.create(org=org, path="orphan.txt")
        channel_layer, channel_name = _subscribe(org.id)

        call_command("prune_storage_files", f"--org-id={org.id}", "--dry-run")

        assert StorageFile.objects.filter(org=org, path="orphan.txt").exists()
        _assert_nothing_received(channel_layer, channel_name)

    def test_prune_no_orphans_emits_nothing(self, org):
        channel_layer, channel_name = _subscribe(org.id)

        call_command("prune_storage_files", f"--org-id={org.id}")

        _assert_nothing_received(channel_layer, channel_name)
