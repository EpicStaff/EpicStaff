import json

import pytest

from tables.models.graph_models import (
    Graph,
    GraphOrganization,
    SessionStorageFile,
    StartNode,
    StorageFile,
)
from tables.models.session_models import Session
from tables.services import redis_pubsub


class _FakeRedis:
    def __init__(self, sets=None):
        self.sets = sets if sets is not None else {}

    def pubsub(self):
        return object()

    def keys(self, pattern):
        return []

    def smembers(self, name):
        return set(self.sets.get(name, set()))

    def delete(self, *names):
        return sum(1 for name in names if self.sets.pop(name, None) is not None)


@pytest.mark.django_db
def test_end_status_writes_back_declared_org_paths(default_org, monkeypatch):
    graph = Graph.objects.create(
        name="pubsub", org=default_org, enable_persistent_variables=True
    )
    StartNode.objects.create(
        graph=graph,
        variables={
            "variables": {"counter": 0},
            "persistent_variables": {"organization": ["counter"], "user": []},
        },
    )
    GraphOrganization.objects.create(graph=graph, persistent_variables={})
    session = Session.objects.create(
        graph=graph, status=Session.SessionStatus.RUN, variables={}
    )

    # avoid a live Redis connection in __init__
    monkeypatch.setattr(
        redis_pubsub.RedisPubSub, "_create_redis_client", lambda self: _FakeRedis()
    )
    # the handler calls close_old_connections(), which would drop the test's
    # transactional DB connection — no-op it so the handler runs to completion
    monkeypatch.setattr(redis_pubsub, "close_old_connections", lambda: None)
    svc = redis_pubsub.RedisPubSub()
    # isolate: storage-files handling is unrelated to variable write-back
    monkeypatch.setattr(svc, "_save_session_storage_files", lambda session: None)

    message = {
        "data": json.dumps(
            {
                "session_id": session.id,
                "status": Session.SessionStatus.END,
                "status_data": {"variables": {"counter": 11}},
            }
        )
    }
    svc.session_status_handler(message)

    assert GraphOrganization.objects.get(graph=graph).persistent_variables == {
        "counter": 11
    }


@pytest.mark.django_db
def test_status_update_for_concurrently_deleted_session_skips_persist(
    default_org, monkeypatch, mocker
):
    """Simulates the bulk_delete race -- the session row still
    exists when session_status_handler's Session.objects.get() runs, but is
    gone (deleted concurrently by bulk_delete) by the time the handler's
    UPDATE runs, so the UPDATE affects 0 rows."""
    graph = Graph.objects.create(name="pubsub-race", org=default_org)
    session = Session.objects.create(
        graph=graph, status=Session.SessionStatus.RUN, variables={}
    )

    # avoid a live Redis connection in __init__
    monkeypatch.setattr(
        redis_pubsub.RedisPubSub, "_create_redis_client", lambda self: _FakeRedis()
    )
    monkeypatch.setattr(redis_pubsub, "close_old_connections", lambda: None)
    svc = redis_pubsub.RedisPubSub()

    persist_mock = mocker.patch.object(
        svc.persistent_variables_service, "persist_session_results"
    )
    save_files_mock = mocker.patch.object(svc, "_save_session_storage_files")

    # Session.objects.get() (used by the handler to fetch the row) still
    # succeeds, but the subsequent filter(pk=...).update(...) call -- the
    # one this fix introduced -- returns 0 rows updated, as it would if
    # bulk_delete's transaction removed the row in between.
    real_filter = redis_pubsub.Session.objects.filter

    def _filter_returning_zero_update(*args, **kwargs):
        qs = real_filter(*args, **kwargs)
        mocker.patch.object(qs, "update", return_value=0)
        return qs

    mocker.patch.object(
        redis_pubsub.Session.objects,
        "filter",
        side_effect=_filter_returning_zero_update,
    )

    message = {
        "data": json.dumps(
            {
                "session_id": session.id,
                "status": Session.SessionStatus.END,
                "status_data": {"variables": {}},
            }
        )
    }

    # Must not raise even though the UPDATE reports 0 affected rows.
    svc.session_status_handler(message)

    persist_mock.assert_not_called()
    save_files_mock.assert_not_called()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "final_status", [Session.SessionStatus.END, Session.SessionStatus.ERROR]
)
def test_final_status_links_session_storage_files(
    default_org, monkeypatch, final_status
):
    graph = Graph.objects.create(name="pubsub-storage", org=default_org)
    session = Session.objects.create(
        graph=graph, status=Session.SessionStatus.RUN, variables={}
    )
    storage_file = StorageFile.objects.create(
        org=default_org,
        path="outputs/report.txt",
        name="report.txt",
        parent_path="outputs/",
    )
    redis_key = f"session:{session.id}:storage_mutations"
    fake_redis = _FakeRedis(
        sets={redis_key: {f"{default_org.id}:{storage_file.path}"}}
    )

    # avoid a live Redis connection in __init__
    monkeypatch.setattr(
        redis_pubsub.RedisPubSub, "_create_redis_client", lambda self: fake_redis
    )
    monkeypatch.setattr(redis_pubsub, "close_old_connections", lambda: None)
    svc = redis_pubsub.RedisPubSub()

    message = {
        "data": json.dumps(
            {
                "session_id": session.id,
                "status": final_status,
                "status_data": {"variables": {}},
            }
        )
    }
    svc.session_status_handler(message)

    assert SessionStorageFile.objects.filter(
        session=session, storage_file=storage_file
    ).exists()
    assert redis_key not in fake_redis.sets


@pytest.mark.django_db
def test_run_status_skips_persist_and_storage_files(
    default_org, monkeypatch, mocker
):
    graph = Graph.objects.create(name="pubsub-run", org=default_org)
    session = Session.objects.create(
        graph=graph, status=Session.SessionStatus.PENDING, variables={}
    )

    # avoid a live Redis connection in __init__
    monkeypatch.setattr(
        redis_pubsub.RedisPubSub, "_create_redis_client", lambda self: _FakeRedis()
    )
    monkeypatch.setattr(redis_pubsub, "close_old_connections", lambda: None)
    svc = redis_pubsub.RedisPubSub()

    persist_mock = mocker.patch.object(
        svc.persistent_variables_service, "persist_session_results"
    )
    save_files_mock = mocker.patch.object(svc, "_save_session_storage_files")

    message = {
        "data": json.dumps(
            {
                "session_id": session.id,
                "status": Session.SessionStatus.RUN,
                "status_data": {"variables": {}},
            }
        )
    }
    svc.session_status_handler(message)

    session.refresh_from_db()
    assert session.status == Session.SessionStatus.RUN
    persist_mock.assert_not_called()
    save_files_mock.assert_not_called()
