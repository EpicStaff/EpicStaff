"""
RunSession must flush the graph's live collab snapshot to the DB
before assembling session data, so Run always executes the latest edits
instead of waiting for the next ~20s autosave tick.

If flush fails, it will still starts, but it will run the previous
successfully saved snapshot
"""

import fakeredis.aioredis
import pytest
from asgiref.sync import async_to_sync
from django.urls import reverse
from rest_framework import status

from tables.graph_collab import graph_state_service as graph_state_service_module
from tables.graph_collab.flush_service import FlushOutcome, FlushStatus, flush_service
from tables.models import Graph, PythonNode, Session, SessionWarningMessage
from tests.fixtures import *  # noqa: F401,F403


@pytest.fixture
def auth_client(api_client, regular_user, default_org):
    """Override the global `auth_client` for this file.

    `RunSessionView` needs a real `request.user` (it's cast to int for
    session bookkeeping), but test settings clear
    `DEFAULT_AUTHENTICATION_CLASSES` so the JWT Bearer header from the
    global `auth_client` is never processed and `request.user` stays
    `AnonymousUser` — "Cannot cast AnonymousUser to int". `force_authenticate`
    bypasses authentication entirely. `regular_user` is an Org Admin member
    of `default_org`, matching the `graph`/`session_data` fixtures
    (`tests/fixtures.py`), which are created in `default_org`.
    """
    api_client.force_authenticate(user=regular_user)
    api_client.credentials(HTTP_X_ORGANIZATION_ID=str(default_org.id))
    return api_client


@pytest.fixture
def fake_async_redis():
    """Fresh fakeredis async client with decode_responses=True."""
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


@pytest.fixture(autouse=True)
def patch_graph_state_redis(fake_async_redis, monkeypatch):
    """Replace the Redis client used by graph_state_service with an in-memory fake,
    mirroring tests/graph_collab/conftest.py — RunSession now calls flush_service.flush,
    which reads the live snapshot through graph_state_service.
    """
    monkeypatch.setattr(
        type(graph_state_service_module.graph_state_service),
        "_redis",
        property(lambda self: fake_async_redis),
    )


def _base_snapshot(**overrides) -> dict:
    """Minimal valid superset snapshot for flush tests."""
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


@pytest.mark.django_db(transaction=True)
def test_run_session_flushes_dirty_live_snapshot_before_running(
    auth_client, redis_client_mock, graph: Graph
):
    """A live-edited node sitting only in the Redis snapshot must be persisted
    to the DB as part of the run request — before the session is assembled —
    so the run is never built from stale DB rows."""
    python_temp_id = "aaaabbbb-0000-0000-0000-000000000099"
    start_temp_id = "aaaabbbb-0000-0000-0000-000000000098"
    snapshot = _base_snapshot(
        save_version=graph.save_version,
        start_node_list=[
            {
                "temp_id": start_temp_id,
                "graph": graph.id,
                "variables": {},
            }
        ],
        python_node_list=[
            {
                "temp_id": python_temp_id,
                "graph": graph.id,
                "python_code": {
                    "code": "def main(): return 42",
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
    async_to_sync(graph_state_service_module.graph_state_service.seed)(
        graph.id, snapshot
    )

    assert PythonNode.objects.filter(graph=graph).count() == 0

    url = reverse("run-session")
    response = auth_client.post(
        url, {"graph_id": graph.id, "variables": {}}, format="json"
    )

    assert response.status_code == status.HTTP_201_CREATED, response.content

    # The live edit must have reached the DB as part of the run request —
    # not on the next autosave tick.
    assert PythonNode.objects.filter(graph=graph).count() == 1
    graph.refresh_from_db()
    assert graph.save_version > 0


@pytest.mark.django_db
def test_run_session_with_no_live_snapshot_still_succeeds(
    auth_client, redis_client_mock, session_data
):
    """When nobody is live-editing the graph, flush() no-ops (NOTHING_TO_FLUSH)
    and the run proceeds exactly as before."""
    url = reverse("run-session")

    response = auth_client.post(url, session_data, format="json")

    assert response.status_code == status.HTTP_201_CREATED, response.content
    session = Session.objects.get(pk=response.data["session_id"])
    assert session.status == "pending"
    assert not SessionWarningMessage.objects.filter(session=session).exists()


@pytest.mark.django_db
def test_run_session_proceeds_with_warning_on_persistent_flush_failure(
    auth_client, redis_client_mock, session_data, monkeypatch
):
    """A persistent flush failure (validation / bulk-save / db error) must not
    block the run — it proceeds on the last-saved DB state and surfaces a
    SessionWarningMessage."""

    async def _failing_flush(self, graph_id):
        return FlushOutcome(status=FlushStatus.FAILED, failure_reason="db_error")

    monkeypatch.setattr(type(flush_service), "flush", _failing_flush)

    url = reverse("run-session")
    response = auth_client.post(url, session_data, format="json")

    assert response.status_code == status.HTTP_201_CREATED, response.content
    session_id = response.data["session_id"]
    warning = SessionWarningMessage.objects.get(session_id=session_id)
    assert any("Could not save the latest live edits" in m for m in warning.messages)


@pytest.mark.django_db
def test_run_session_proceeds_without_warning_on_version_conflict(
    auth_client, redis_client_mock, session_data, monkeypatch
):
    """A transient version_conflict FAILED outcome means a concurrent save
    already won — the DB is current, so the run must proceed silently
    (no SessionWarningMessage)."""

    async def _conflicted_flush(self, graph_id):
        return FlushOutcome(
            status=FlushStatus.FAILED, failure_reason="version_conflict"
        )

    monkeypatch.setattr(type(flush_service), "flush", _conflicted_flush)

    url = reverse("run-session")
    response = auth_client.post(url, session_data, format="json")

    assert response.status_code == status.HTTP_201_CREATED, response.content
    session_id = response.data["session_id"]
    assert not SessionWarningMessage.objects.filter(session_id=session_id).exists()


@pytest.mark.django_db
def test_run_session_proceeds_with_warning_on_unexpected_flush_exception(
    auth_client, redis_client_mock, session_data, monkeypatch
):
    """An unexpected exception from flush() (e.g. Redis/DB transiently down) must
    not break Run — the view degrades gracefully: proceed on the last-saved DB
    state and surface the same warning as a persistent FAILED outcome."""

    async def _raising_flush(self, graph_id):
        raise RuntimeError("redis transiently unavailable")

    monkeypatch.setattr(type(flush_service), "flush", _raising_flush)

    url = reverse("run-session")
    response = auth_client.post(url, session_data, format="json")

    assert response.status_code == status.HTTP_201_CREATED, response.content
    session_id = response.data["session_id"]
    warning = SessionWarningMessage.objects.get(session_id=session_id)
    assert any("Could not save the latest live edits" in m for m in warning.messages)
