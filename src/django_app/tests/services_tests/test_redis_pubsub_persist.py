import json
from datetime import timedelta

import fakeredis
import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from tables.models import SessionStorageFile, StorageFile
from tables.models.graph_models import Graph, GraphOrganization, StartNode
from tables.models.session_models import Session
from tables.services import redis_pubsub


@pytest.fixture
def pubsub_with_redis(monkeypatch):
    redis_client = fakeredis.FakeRedis(decode_responses=True)
    # avoid a live Redis connection in __init__
    monkeypatch.setattr(
        redis_pubsub.RedisPubSub, "_create_redis_client", lambda self: redis_client
    )
    # the handler calls close_old_connections(), which would drop the test's
    # transactional DB connection — no-op it so the handler runs to completion
    monkeypatch.setattr(redis_pubsub, "close_old_connections", lambda: None)
    yield redis_pubsub.RedisPubSub(), redis_client


@pytest.fixture
def running_session(default_org):
    graph = Graph.objects.create(name="pubsub", org=default_org)
    yield Session.objects.create(
        graph=graph, status=Session.SessionStatus.RUN, variables={}
    )


def _status_message(session_id, status, **status_data):
    return {
        "data": json.dumps(
            {"session_id": session_id, "status": status, "status_data": status_data}
        )
    }


def _store_final_variables(redis_client, session_id, variables):
    redis_client.set(
        f"session:{session_id}:final_variables", json.dumps(variables), ex=900
    )


def _fail_with_a_database_error(*args, **kwargs):
    # A real failing statement: on Postgres it aborts the enclosing transaction,
    # which is what a plain mocked exception would not reproduce.
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1 / 0")


@pytest.mark.django_db
def test_end_status_stores_variables_read_from_the_final_variables_key(
    pubsub_with_redis, running_session
):
    pubsub, redis_client = pubsub_with_redis
    _store_final_variables(
        redis_client, running_session.id, {"final_result": "done", "counter": 3}
    )

    pubsub.session_status_handler(
        _status_message(running_session.id, Session.SessionStatus.END)
    )

    running_session.refresh_from_db()
    assert running_session.status == Session.SessionStatus.END
    assert running_session.finished_at is not None
    assert running_session.status_data["variables"] == {
        "final_result": "done",
        "counter": 3,
    }
    assert "total_token_usage" in running_session.status_data
    # The key is left to expire, so a second reader still finds it.
    assert redis_client.exists(f"session:{running_session.id}:final_variables")


@pytest.mark.django_db
def test_end_status_handled_twice_keeps_the_variables(
    pubsub_with_redis, running_session
):
    pubsub, redis_client = pubsub_with_redis
    _store_final_variables(redis_client, running_session.id, {"final_result": "done"})
    message = _status_message(running_session.id, Session.SessionStatus.END)

    pubsub.session_status_handler(message)
    pubsub.session_status_handler(message)

    running_session.refresh_from_db()
    assert running_session.status == Session.SessionStatus.END
    assert running_session.status_data["variables"] == {"final_result": "done"}


@pytest.mark.django_db
def test_run_status_stores_no_variables(pubsub_with_redis, running_session):
    pubsub, redis_client = pubsub_with_redis
    _store_final_variables(redis_client, running_session.id, {"final_result": "stale"})

    pubsub.session_status_handler(
        _status_message(running_session.id, Session.SessionStatus.RUN)
    )

    running_session.refresh_from_db()
    assert running_session.status == Session.SessionStatus.RUN
    assert "variables" not in running_session.status_data


@pytest.mark.django_db
def test_end_status_without_stored_variables_still_ends_the_session(
    pubsub_with_redis, running_session
):
    pubsub, _ = pubsub_with_redis

    pubsub.session_status_handler(
        _status_message(running_session.id, Session.SessionStatus.END)
    )

    running_session.refresh_from_db()
    assert running_session.status == Session.SessionStatus.END
    assert running_session.finished_at is not None
    assert "variables" not in running_session.status_data


@pytest.mark.django_db
def test_run_then_end_writes_back_declared_org_paths(default_org, pubsub_with_redis):
    pubsub, redis_client = pubsub_with_redis
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
        graph=graph, status=Session.SessionStatus.PENDING, variables={}
    )

    # The real sequence: the session row is still RUN when `end` arrives.
    pubsub.session_status_handler(
        _status_message(session.id, Session.SessionStatus.RUN)
    )
    _store_final_variables(redis_client, session.id, {"counter": 11})
    pubsub.session_status_handler(
        _status_message(session.id, Session.SessionStatus.END)
    )

    assert GraphOrganization.objects.get(graph=graph).persistent_variables == {
        "counter": 11
    }


@pytest.mark.django_db
def test_error_status_links_the_files_the_session_wrote(
    default_org, pubsub_with_redis, running_session
):
    pubsub, redis_client = pubsub_with_redis
    storage_file = StorageFile.objects.create(
        org=default_org, path="report.txt", name="report.txt"
    )
    redis_client.sadd(
        f"session:{running_session.id}:storage_mutations",
        f"{default_org.id}:report.txt",
    )

    pubsub.session_status_handler(
        _status_message(
            running_session.id, Session.SessionStatus.ERROR, error="node crashed"
        )
    )

    assert list(
        SessionStorageFile.objects.filter(session=running_session).values_list(
            "storage_file_id", flat=True
        )
    ) == [storage_file.id]


@pytest.mark.django_db
def test_status_update_for_concurrently_deleted_session_skips_persist(
    pubsub_with_redis, running_session, mocker
):
    """Simulates the bulk_delete race -- the session row still
    exists when session_status_handler's Session.objects.get() runs, but is
    gone (deleted concurrently by bulk_delete) by the time the handler's
    UPDATE runs, so the UPDATE affects 0 rows."""
    pubsub, redis_client = pubsub_with_redis
    _store_final_variables(redis_client, running_session.id, {"counter": 1})

    persist_mock = mocker.patch.object(
        pubsub.persistent_variables_service, "persist_session_results"
    )
    save_files_mock = mocker.patch.object(pubsub, "_save_session_storage_files")

    # Session.objects.get() (used by the handler to fetch the row) still
    # succeeds, but the subsequent filter(pk=...).update(...) call
    # returns 0 rows updated, as it would if bulk_delete's transaction
    # removed the row in between.
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

    # Must not raise even though the UPDATE reports 0 affected rows.
    pubsub.session_status_handler(
        _status_message(running_session.id, Session.SessionStatus.END)
    )

    persist_mock.assert_not_called()
    save_files_mock.assert_not_called()


@pytest.mark.django_db
def test_end_status_is_committed_when_persisting_results_hits_a_database_error(
    default_org, pubsub_with_redis, running_session, mocker
):
    pubsub, redis_client = pubsub_with_redis
    _store_final_variables(redis_client, running_session.id, {"final_result": "done"})
    storage_file = StorageFile.objects.create(
        org=default_org, path="report.txt", name="report.txt"
    )
    redis_client.sadd(
        f"session:{running_session.id}:storage_mutations",
        f"{default_org.id}:report.txt",
    )
    mocker.patch.object(
        pubsub.persistent_variables_service,
        "persist_session_results",
        side_effect=_fail_with_a_database_error,
    )

    pubsub.session_status_handler(
        _status_message(running_session.id, Session.SessionStatus.END)
    )

    running_session.refresh_from_db()
    assert running_session.status == Session.SessionStatus.END
    assert running_session.finished_at is not None
    assert running_session.status_data["variables"] == {"final_result": "done"}
    # The failed step does not take the next one down with it.
    assert list(
        SessionStorageFile.objects.filter(session=running_session).values_list(
            "storage_file_id", flat=True
        )
    ) == [storage_file.id]


@pytest.mark.django_db
def test_end_status_is_committed_when_linking_storage_files_hits_a_database_error(
    default_org, pubsub_with_redis, running_session, mocker
):
    pubsub, redis_client = pubsub_with_redis
    _store_final_variables(redis_client, running_session.id, {"final_result": "done"})
    StorageFile.objects.create(org=default_org, path="report.txt", name="report.txt")
    redis_client.sadd(
        f"session:{running_session.id}:storage_mutations",
        f"{default_org.id}:report.txt",
    )
    # _save_session_storage_files swallows this error itself, so only the
    # savepoint around it can keep the aborted transaction from undoing `end`.
    mocker.patch.object(
        redis_pubsub.SessionStorageFile.objects,
        "bulk_create",
        side_effect=_fail_with_a_database_error,
    )

    pubsub.session_status_handler(
        _status_message(running_session.id, Session.SessionStatus.END)
    )

    running_session.refresh_from_db()
    assert running_session.status == Session.SessionStatus.END
    assert running_session.finished_at is not None
    assert running_session.status_data["variables"] == {"final_result": "done"}
    assert not SessionStorageFile.objects.filter(session=running_session).exists()


@pytest.mark.django_db
def test_status_handler_locks_the_session_without_reading_its_large_json_fields(
    pubsub_with_redis, running_session
):
    pubsub, _redis_client = pubsub_with_redis

    with CaptureQueriesContext(connection) as captured:
        pubsub.session_status_handler(
            _status_message(running_session.id, Session.SessionStatus.WAIT_FOR_USER)
        )

    [locking_query] = [
        query["sql"] for query in captured.captured_queries if "FOR NO KEY UPDATE" in query["sql"]
    ]
    for large_field in ("graph_schema", "variables", "status_data"):
        assert f'"tables_session"."{large_field}"' not in locking_query
    running_session.refresh_from_db()
    assert running_session.status == Session.SessionStatus.WAIT_FOR_USER


def _set_status_updated_at(session, moment):
    Session.objects.filter(pk=session.pk).update(status_updated_at=moment)


@pytest.mark.django_db
def test_status_change_restarts_the_time_to_live_clock(pubsub_with_redis, running_session):
    pubsub, _redis_client = pubsub_with_redis
    an_hour_ago = timezone.now() - timedelta(hours=1)
    _set_status_updated_at(running_session, an_hour_ago)

    pubsub.session_status_handler(
        _status_message(running_session.id, Session.SessionStatus.WAIT_FOR_USER)
    )

    running_session.refresh_from_db()
    assert running_session.status_updated_at > an_hour_ago + timedelta(minutes=59)


@pytest.mark.django_db
def test_repeated_status_does_not_restart_the_time_to_live_clock(
    pubsub_with_redis, running_session
):
    pubsub, _redis_client = pubsub_with_redis
    an_hour_ago = timezone.now() - timedelta(hours=1)
    _set_status_updated_at(running_session, an_hour_ago)

    pubsub.session_status_handler(_status_message(running_session.id, Session.SessionStatus.RUN))

    running_session.refresh_from_db()
    assert running_session.status_updated_at == an_hour_ago

