"""Restoring a graph version resets the live collaborative
session: co-editors' canvases rebuild via a `graph_state` broadcast, the Redis
snapshot is reseeded to the restored graph's new ids, and stale locks are
cleared.

Self-contained: does NOT import or depend on tests/graph_collab/conftest.py.
Redis is faked the same way as the known-good tests/api_tests/run_session_flush_test.py.
WebSocket broadcasts are captured by patching GraphEditNotifier._send (the
single choke-point all HTTP-path broadcasts go through) with a recording
mock, rather than exercising a real/fake channel layer.
"""

import fakeredis.aioredis
import pytest
from asgiref.sync import async_to_sync
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from tables.graph_collab import graph_state_service as graph_state_service_module
from tables.graph_collab.flush_service import FlushOutcome, FlushStatus, flush_service
from tables.graph_collab.lock_service import lock_service
from tables.graph_collab.notifications import GraphEditNotifier
from tables.graph_collab.presence_service import presence_service
from tables.graph_collab.protocol import EditorInfo
from tables.models import Graph, GraphVersion, PythonNode
from tests.fixtures import *  # noqa: F401,F403

graph_state_service = graph_state_service_module.graph_state_service


# ---------------------------------------------------------------------------
# Self-contained fixtures — no dependency on tests/graph_collab/conftest.py
# ---------------------------------------------------------------------------


@pytest.fixture
def auth_client(regular_user, default_org) -> APIClient:
    """force_authenticate-based client — does not rely on JWT settings.

    Also sends the active-org header: `GraphVersionViewSet` is org-scoped
    (`OrgScopedChildViewSetMixin`) and resolves the active org via
    `OrgContextService`, which requires either a URL `org_id` kwarg or the
    `X-Organization-Id` header — omitting it fails every request here with
    400 `org_context_required`. `regular_user` is an Org Admin member of
    `default_org`, matching the `graph` fixture (`tests/fixtures.py`), which
    is created in `default_org`.
    """
    client = APIClient()
    client.force_authenticate(user=regular_user)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(default_org.id))
    return client


@pytest.fixture
def second_user(db):
    """A second distinct user, for multi-editor presence scenarios."""
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(
        email="second-editor@example.com",
        password="SecondUserStrongPass123!",
    )


@pytest.fixture
def fake_async_redis():
    """Fresh fakeredis async client with decode_responses=True."""
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


@pytest.fixture(autouse=True)
def patch_graph_state_redis(fake_async_redis, monkeypatch):
    """Replace the Redis client used by graph_state_service with an in-memory
    fake, mirroring tests/api_tests/run_session_flush_test.py.

    GraphVersionViewSet.create/restore call flush_service.flush and
    graph_state_service.get_snapshot/reset_from_db, which all read/write the
    live collab snapshot through graph_state_service's Redis client.
    """
    monkeypatch.setattr(
        type(graph_state_service),
        "_redis",
        property(lambda self: fake_async_redis),
    )


@pytest.fixture(autouse=True)
def reset_lock_store():
    """Reset the module-level lock store around each test to prevent leakage."""
    lock_service._store.clear()
    yield
    lock_service._store.clear()


@pytest.fixture(autouse=True)
def reset_graph_state_in_memory_counters():
    """Reset graph_state_service's per-process in-memory maps around each test."""
    graph_state_service._locks.clear()
    graph_state_service._revision.clear()
    graph_state_service._flushed_revision.clear()
    yield
    graph_state_service._locks.clear()
    graph_state_service._revision.clear()
    graph_state_service._flushed_revision.clear()


@pytest.fixture(autouse=True)
def reset_presence_store():
    """Reset the module-level presence store around each test to prevent leakage."""
    presence_service._store.clear()
    yield
    presence_service._store.clear()


@pytest.fixture
def captured_broadcasts(mocker):
    """Record every (graph_id, message_dict) sent via GraphEditNotifier._send.

    ``_send`` is the single choke-point all HTTP-path broadcasts go through
    (graph_saved, graph_state, node_unlocked), so patching it here captures
    everything without needing a real/fake channel layer.
    """
    calls: list[tuple[int, dict]] = []

    def _record(graph_id: int, message: dict) -> None:
        calls.append((graph_id, message))

    mocker.patch.object(GraphEditNotifier, "_send", side_effect=_record)
    return calls


def _messages_of_type(calls: list[tuple[int, dict]], message_type: str) -> list[dict]:
    return [message for _, message in calls if message["type"] == message_type]


# ---------------------------------------------------------------------------
# Snapshot helpers
# ---------------------------------------------------------------------------


def _base_snapshot(**overrides) -> dict:
    """Minimal valid superset snapshot (mirrors run_session_flush_test.py)."""
    empty_deleted = {
        "edge_ids": [],
        "conditional_edge_ids": [],
        "crew_node_ids": [],
        "python_node_ids": [],
        "file_extractor_node_ids": [],
        "audio_transcription_node_ids": [],
        "start_node_ids": [],
        "end_node_ids": [],
        "subgraph_node_ids": [],
        "decision_table_node_ids": [],
        "graph_note_ids": [],
        "webhook_trigger_node_ids": [],
        "telegram_trigger_node_ids": [],
        "schedule_trigger_node_ids": [],
        "code_agent_node_ids": [],
    }
    base = {
        "save_version": 0,
        "crew_node_list": [],
        "python_node_list": [],
        "file_extractor_node_list": [],
        "audio_transcription_node_list": [],
        "start_node_list": [],
        "end_node_list": [],
        "subgraph_node_list": [],
        "decision_table_node_list": [],
        "graph_note_list": [],
        "webhook_trigger_node_list": [],
        "telegram_trigger_node_list": [],
        "schedule_trigger_node_list": [],
        "code_agent_node_list": [],
        "edge_list": [],
        "conditional_edge_list": [],
        "deleted": empty_deleted,
    }
    base.update(overrides)
    return base


def _live_edit_snapshot(graph: Graph) -> dict:
    """A snapshot carrying one not-yet-persisted PythonNode + StartNode edit."""
    python_temp_id = "aaaabbbb-0000-0000-0000-000000000099"
    start_temp_id = "aaaabbbb-0000-0000-0000-000000000098"
    return _base_snapshot(
        save_version=graph.save_version,
        start_node_list=[
            {"temp_id": start_temp_id, "graph": graph.id, "variables": {}}
        ],
        python_node_list=[
            {
                "temp_id": python_temp_id,
                "graph": graph.id,
                "python_code": {
                    "code": "def main(): return 'live-edit'",
                    "entrypoint": "main",
                    "libraries": [],
                },
            }
        ],
        edge_list=[
            {
                "temp_id": "edge-0000-0000-0000-000000000097",
                "graph": graph.id,
                "start_temp_id": start_temp_id,
                "end_temp_id": python_temp_id,
            }
        ],
    )


@pytest.fixture
def make_graph_version(auth_client, graph):
    def _make(*, name="test-version", description=""):
        payload = {"graph_id": graph.id, "name": name, "description": description}
        response = auth_client.post(
            reverse("graph-versions-list"), payload, format="json"
        )
        assert response.status_code == status.HTTP_201_CREATED, response.content
        return response.data

    return _make


def _restore(auth_client, version_id, save_version, *, backup=False):
    url = reverse("graph-versions-restore", args=[version_id])
    if backup:
        url += "?backup=true"
    return auth_client.post(url, {"save_version": save_version}, format="json")


# ---------------------------------------------------------------------------
# (a) Reset on restore with a live session
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_restore_with_live_session_resets_snapshot_and_broadcasts(
    auth_client, graph, regular_user, make_graph_version, captured_broadcasts
):
    version = make_graph_version(name="snap-for-reset")
    version_id = version["id"]
    graph.refresh_from_db()

    editor = EditorInfo(user_id=regular_user.pk, display_name="Alice", avatar_url=None)
    lock_service.try_lock(graph.id, "stale-node", "label", editor, "chan-1")

    async_to_sync(graph_state_service.seed)(graph.id, _live_edit_snapshot(graph))

    response = _restore(auth_client, version_id, graph.save_version)
    assert response.status_code == status.HTTP_200_OK, response.content

    # Redis snapshot cleared & reseeded to the restored graph's ids — the live
    # edit's temp-id node must be gone; the restored version had none.
    restored_snapshot = async_to_sync(graph_state_service.get_snapshot)(graph.id)
    assert restored_snapshot is not None
    assert restored_snapshot["python_node_list"] == []

    graph.refresh_from_db()
    graph_state_messages = _messages_of_type(captured_broadcasts, "graph_state")
    assert len(graph_state_messages) == 1
    message = graph_state_messages[0]
    assert message["restored_by"]["user_id"] == regular_user.pk
    assert message["new_save_version"] == graph.save_version
    assert message["version_name"] == "snap-for-reset"

    # Stale lock is gone, and a node_unlocked broadcast was sent for it.
    assert lock_service.get_holder(graph.id, "stale-node", "label") is None
    unlocked_messages = _messages_of_type(captured_broadcasts, "node_unlocked")
    assert len(unlocked_messages) == 1
    assert unlocked_messages[0]["node_id"] == "stale-node"
    assert unlocked_messages[0]["field"] == "label"


@pytest.mark.django_db
def test_restore_with_live_session_releases_all_locks_for_the_graph(
    auth_client, graph, regular_user, make_graph_version, captured_broadcasts
):
    """release_all coverage: multiple locks across multiple nodes are all
    released and all broadcast, none left behind."""
    version = make_graph_version(name="snap-for-multi-unlock")
    version_id = version["id"]
    graph.refresh_from_db()

    editor = EditorInfo(user_id=regular_user.pk, display_name="Alice", avatar_url=None)
    lock_service.try_lock(graph.id, "node-a", "label", editor, "chan-1")
    lock_service.try_lock(graph.id, "node-a", "description", editor, "chan-1")
    lock_service.try_lock(graph.id, "node-b", "label", editor, "chan-2")

    async_to_sync(graph_state_service.seed)(graph.id, _live_edit_snapshot(graph))

    response = _restore(auth_client, version_id, graph.save_version)
    assert response.status_code == status.HTTP_200_OK, response.content

    assert lock_service.get_all_locks(graph.id) == {}
    unlocked_pairs = {
        (message["node_id"], message["field"])
        for message in _messages_of_type(captured_broadcasts, "node_unlocked")
    }
    assert unlocked_pairs == {
        ("node-a", "label"),
        ("node-a", "description"),
        ("node-b", "label"),
    }


# ---------------------------------------------------------------------------
# (b) No live session
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_restore_without_live_session_does_not_broadcast_or_clear(
    auth_client, graph, make_graph_version, captured_broadcasts
):
    version = make_graph_version(name="snap-no-session")
    version_id = version["id"]
    graph.refresh_from_db()

    response = _restore(auth_client, version_id, graph.save_version)

    assert response.status_code == status.HTTP_200_OK, response.content
    assert response.data["restored"] is True
    assert _messages_of_type(captured_broadcasts, "graph_state") == []
    assert _messages_of_type(captured_broadcasts, "node_unlocked") == []
    assert async_to_sync(graph_state_service.get_snapshot)(graph.id) is None


# ---------------------------------------------------------------------------
# (c) Flush-fidelity
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_restore_with_backup_flushes_live_edit_into_auto_backup(
    auth_client, graph, make_graph_version
):
    version = make_graph_version(name="snap-before-live-edit")
    version_id = version["id"]
    graph.refresh_from_db()

    assert PythonNode.objects.filter(graph=graph).count() == 0
    async_to_sync(graph_state_service.seed)(graph.id, _live_edit_snapshot(graph))

    response = _restore(auth_client, version_id, graph.save_version, backup=True)
    assert response.status_code == status.HTTP_200_OK, response.content

    auto_backup_id = response.data["auto_backup_version_id"]
    assert auto_backup_id is not None
    backup = GraphVersion.objects.get(id=auto_backup_id)
    backup_python_nodes = [
        node for node in backup.snapshot["nodes"] if node["node_type"] == "PythonNode"
    ]
    assert len(backup_python_nodes) == 1
    assert (
        backup_python_nodes[0]["python_code"]["code"]
        == "def main(): return 'live-edit'"
    )


# ---------------------------------------------------------------------------
# Backup policy — multi-editor gate
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_restore_solo_editor_with_backup_false_does_not_force_backup(
    auth_client, graph, regular_user, make_graph_version, captured_broadcasts
):
    """Solo editor + explicit backup=false → backup stays client-controlled
    (no new backup GraphVersion), but the live-session reset/broadcast still
    runs — that gate is independent of the backup decision."""
    version = make_graph_version(name="snap-solo")
    version_id = version["id"]
    graph.refresh_from_db()

    editor = EditorInfo(user_id=regular_user.pk, display_name="Alice", avatar_url=None)
    presence_service.add(graph.id, "chan-a", editor)
    async_to_sync(graph_state_service.seed)(graph.id, _live_edit_snapshot(graph))

    versions_before = GraphVersion.objects.filter(graph=graph).count()
    response = _restore(auth_client, version_id, graph.save_version, backup=False)

    assert response.status_code == status.HTTP_200_OK, response.content
    assert response.data["auto_backup_version_id"] is None
    assert GraphVersion.objects.filter(graph=graph).count() == versions_before

    # has_live_session gate is unaffected by the backup decision.
    assert async_to_sync(graph_state_service.get_snapshot)(graph.id) is not None
    assert len(_messages_of_type(captured_broadcasts, "graph_state")) == 1


@pytest.mark.django_db
def test_restore_two_distinct_editors_forces_backup_even_with_backup_false(
    auth_client, graph, regular_user, second_user, make_graph_version
):
    version = make_graph_version(name="snap-multi-editor")
    version_id = version["id"]
    graph.refresh_from_db()

    editor_one = EditorInfo(
        user_id=regular_user.pk, display_name="Alice", avatar_url=None
    )
    editor_two = EditorInfo(user_id=second_user.pk, display_name="Bob", avatar_url=None)
    presence_service.add(graph.id, "chan-a", editor_one)
    presence_service.add(graph.id, "chan-b", editor_two)
    async_to_sync(graph_state_service.seed)(graph.id, _live_edit_snapshot(graph))

    response = _restore(auth_client, version_id, graph.save_version, backup=False)

    assert response.status_code == status.HTTP_200_OK, response.content
    auto_backup_id = response.data["auto_backup_version_id"]
    assert auto_backup_id is not None
    assert GraphVersion.objects.filter(id=auto_backup_id).exists()


@pytest.mark.django_db
def test_restore_two_channels_same_user_is_treated_as_solo(
    auth_client, graph, regular_user, make_graph_version
):
    """get_editors() dedups by user_id — two tabs of the same user must not
    be counted as two distinct editors."""
    version = make_graph_version(name="snap-two-tabs-same-user")
    version_id = version["id"]
    graph.refresh_from_db()

    editor = EditorInfo(user_id=regular_user.pk, display_name="Alice", avatar_url=None)
    presence_service.add(graph.id, "chan-a", editor)
    presence_service.add(graph.id, "chan-b", editor)
    async_to_sync(graph_state_service.seed)(graph.id, _live_edit_snapshot(graph))

    versions_before = GraphVersion.objects.filter(graph=graph).count()
    response = _restore(auth_client, version_id, graph.save_version, backup=False)

    assert response.status_code == status.HTTP_200_OK, response.content
    assert response.data["auto_backup_version_id"] is None
    assert GraphVersion.objects.filter(graph=graph).count() == versions_before


@pytest.mark.django_db
def test_restore_forces_backup_when_presence_read_raises_runtime_error(
    auth_client, graph, make_graph_version, monkeypatch
):
    """Fail-safe: if reading presence raises (concurrent WS connect/disconnect
    mutating the dict mid-iteration), assume multiple editors and force the
    backup rather than risk silently losing someone else's unsaved work."""
    version = make_graph_version(name="snap-presence-race")
    version_id = version["id"]
    graph.refresh_from_db()

    def _raising_get_editors(self, graph_id):
        raise RuntimeError("dictionary changed size during iteration")

    monkeypatch.setattr(type(presence_service), "get_editors", _raising_get_editors)
    async_to_sync(graph_state_service.seed)(graph.id, _live_edit_snapshot(graph))

    response = _restore(auth_client, version_id, graph.save_version, backup=False)

    assert response.status_code == status.HTTP_200_OK, response.content
    assert response.data["auto_backup_version_id"] is not None


@pytest.mark.django_db
def test_restore_solo_editor_backup_false_skips_flush(
    auth_client, graph, regular_user, make_graph_version, mocker
):
    """No backup is being taken → flushing first would be wasted work (its
    effect is wiped by the restore with nothing capturing it) — flush must
    not be called, and the version bump must be exactly +1 (from restore
    alone, not +1 from a skipped-but-still-bumping flush)."""
    version = make_graph_version(name="snap-skip-flush")
    version_id = version["id"]
    graph.refresh_from_db()
    save_version_before = graph.save_version

    editor = EditorInfo(user_id=regular_user.pk, display_name="Alice", avatar_url=None)
    presence_service.add(graph.id, "chan-a", editor)
    async_to_sync(graph_state_service.seed)(graph.id, _live_edit_snapshot(graph))

    flush_spy = mocker.patch.object(flush_service, "flush", wraps=flush_service.flush)

    response = _restore(auth_client, version_id, graph.save_version, backup=False)

    assert response.status_code == status.HTTP_200_OK, response.content
    flush_spy.assert_not_called()
    graph.refresh_from_db()
    assert graph.save_version == save_version_before + 1


# ---------------------------------------------------------------------------
# (d) Optimistic conflict
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_restore_stale_save_version_returns_409_before_flush(
    auth_client, graph, make_graph_version, mocker
):
    version = make_graph_version(name="snap-for-conflict")
    version_id = version["id"]

    Graph.objects.filter(pk=graph.pk).update(save_version=50)
    flush_spy = mocker.patch.object(flush_service, "flush", wraps=flush_service.flush)

    response = _restore(auth_client, version_id, 1)  # stale

    assert response.status_code == status.HTTP_409_CONFLICT, response.content
    flush_spy.assert_not_called()
    graph.refresh_from_db()
    assert graph.save_version == 50


# ---------------------------------------------------------------------------
# (e) Persistent flush failure aborts the restore
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_restore_aborts_on_persistent_flush_failure(
    auth_client, graph, make_graph_version, monkeypatch
):
    """Backup=True (explicit) so the flush actually runs — the backup-policy
    change (see the "Backup policy" section above) makes flush conditional
    on backup being taken, so this scenario needs to force it."""
    version = make_graph_version(name="snap-for-flush-failure")
    version_id = version["id"]
    graph.refresh_from_db()

    async def _failing_flush(self, graph_id):
        return FlushOutcome(status=FlushStatus.FAILED, failure_reason="db_error")

    monkeypatch.setattr(type(flush_service), "flush", _failing_flush)

    save_version_before = graph.save_version
    versions_before = GraphVersion.objects.filter(graph=graph).count()
    response = _restore(auth_client, version_id, graph.save_version, backup=True)

    assert response.status_code == 422, response.content
    graph.refresh_from_db()
    assert graph.save_version == save_version_before
    assert GraphVersion.objects.filter(graph=graph).count() == versions_before


# ---------------------------------------------------------------------------
# (f) Protocol back-compat
# ---------------------------------------------------------------------------


def test_graph_state_message_without_restore_fields_still_validates():
    from tables.graph_collab.protocol import GraphStateMessage

    message = GraphStateMessage(flow={"crew_node_list": []})

    assert message.restored_by is None
    assert message.new_save_version is None
    assert message.version_name is None


# ---------------------------------------------------------------------------
# (g) Part E — flush-fidelity on version create
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_create_version_during_live_session_flushes_live_edit_first(
    auth_client, graph, regular_user
):
    async_to_sync(graph_state_service.seed)(graph.id, _live_edit_snapshot(graph))

    # A held lock is part of the "live session" state that create() must NOT
    # touch — unlike restore(), it does not reset the session or release locks.
    editor = EditorInfo(user_id=regular_user.pk, display_name="Alice", avatar_url=None)
    lock_service.try_lock(graph.id, "some-node", "label", editor, "chan-1")

    payload = {"graph_id": graph.id, "name": "created-during-live-session"}
    response = auth_client.post(reverse("graph-versions-list"), payload, format="json")

    assert response.status_code == status.HTTP_201_CREATED, response.content
    version = GraphVersion.objects.get(id=response.data["id"])
    python_nodes = [
        node for node in version.snapshot["nodes"] if node["node_type"] == "PythonNode"
    ]
    assert len(python_nodes) == 1
    assert python_nodes[0]["python_code"]["code"] == "def main(): return 'live-edit'"
    # Non-destructive: the live snapshot is left in place (flushed and
    # reconciled), not cleared.
    assert async_to_sync(graph_state_service.get_snapshot)(graph.id) is not None
    # Non-destructive: create() must not reset the live session — the lock
    # held by an editor before the request stays held afterwards.
    held_lock = lock_service.get_holder(graph.id, "some-node", "label")
    assert held_lock is not None
    assert held_lock.editor == editor


# ---------------------------------------------------------------------------
# (h) Loop-affinity RuntimeError fallback
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_restore_survives_loop_affinity_race_and_falls_back_to_db_serializer(
    auth_client,
    graph,
    regular_user,
    make_graph_version,
    monkeypatch,
    captured_broadcasts,
):
    """A cross-event-loop asyncio.Lock RuntimeError from reset_from_db (the
    documented residual race with a concurrent WS connect) must not fail the
    restore — the restore already committed. The broadcast falls back to
    GraphSerializer(graph).data instead of the view's own reseed."""
    version = make_graph_version(name="snap-for-race")
    version_id = version["id"]
    graph.refresh_from_db()

    async_to_sync(graph_state_service.seed)(graph.id, _live_edit_snapshot(graph))

    async def _raising_reset_from_db(self, graph_id):
        raise RuntimeError(
            "Lock is bound to a different event loop (simulated loop-affinity race)"
        )

    monkeypatch.setattr(
        type(graph_state_service), "reset_from_db", _raising_reset_from_db
    )

    response = _restore(auth_client, version_id, graph.save_version)

    assert response.status_code == status.HTTP_200_OK, response.content

    graph_state_messages = _messages_of_type(captured_broadcasts, "graph_state")
    assert len(graph_state_messages) == 1
    message = graph_state_messages[0]
    assert message["restored_by"]["user_id"] == regular_user.pk
    # The restored version had no python nodes — the DB-serializer fallback
    # must reflect the restored DB state, not the pre-restore live edit.
    assert message["flow"]["python_node_list"] == []
