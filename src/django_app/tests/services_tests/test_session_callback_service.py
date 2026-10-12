import json
import uuid
from unittest.mock import MagicMock

import fakeredis
import pytest
from django.utils import timezone

from tables.models import GraphSessionMessage, Session, SessionCallback
from tables.services import redis_pubsub
from tables.services.redis_pubsub import RedisPubSub
from tables.services.session_callbacks.service import SessionCallbackService
from tests.fixtures import *

USAGE = {"total_tokens": 42, "prompt_tokens": 40, "completion_tokens": 2}


def _register(session):
    return SessionCallback.objects.create(session=session, url="http://chat:8000/cb", secret="s" * 32)


def _graph_end(session, end_node_result):
    return GraphSessionMessage.objects.create(
        session=session,
        created_at=timezone.now(),
        name="__end_node__",
        execution_order=1,
        message_data={"message_type": "graph_end", "end_node_result": end_node_result},
        uuid=uuid.uuid4(),
    )


@pytest.mark.django_db
def test_enqueue_end_builds_payload_with_result(session):
    _register(session)
    _graph_end(session, {"reply": "hi"})

    moved = SessionCallbackService().enqueue(session_id=session.pk, status="end", token_usage=USAGE)

    callback = SessionCallback.objects.get(session=session)
    assert moved is True
    assert callback.status == SessionCallback.Status.PENDING
    assert callback.next_attempt_at is not None
    assert callback.payload["session_id"] == session.pk
    assert callback.payload["graph_id"] == session.graph_id
    assert callback.payload["status"] == "end"
    assert callback.payload["end_node_result"] == {"reply": "hi"}
    assert callback.payload["token_usage"] == USAGE
    assert callback.payload["finished_at"]


@pytest.mark.django_db
def test_enqueue_error_has_null_result(session):
    _register(session)

    SessionCallbackService().enqueue(session_id=session.pk, status="error", token_usage={})

    callback = SessionCallback.objects.get(session=session)
    assert callback.status == SessionCallback.Status.PENDING
    assert callback.payload["end_node_result"] is None


@pytest.mark.django_db
def test_enqueue_without_registration_is_noop(session):
    moved = SessionCallbackService().enqueue(session_id=session.pk, status="end", token_usage={})

    assert moved is False
    assert not SessionCallback.objects.exists()


@pytest.mark.django_db
def test_enqueue_non_terminal_status_is_noop(session):
    _register(session)

    moved = SessionCallbackService().enqueue(session_id=session.pk, status="run", token_usage={})

    assert moved is False
    assert SessionCallback.objects.get(session=session).status == SessionCallback.Status.REGISTERED


@pytest.mark.django_db
def test_enqueue_twice_moves_once(session):
    _register(session)
    service = SessionCallbackService()

    first = service.enqueue(session_id=session.pk, status="end", token_usage=USAGE)
    second = service.enqueue(session_id=session.pk, status="expired", token_usage=USAGE)

    assert (first, second) == (True, False)
    assert SessionCallback.objects.get(session=session).payload["status"] == "end"


@pytest.fixture(autouse=True)
def keep_test_connection(monkeypatch):
    # close_old_connections() would drop the test's transactional connection.
    monkeypatch.setattr(redis_pubsub, "close_old_connections", lambda: None)


def _pubsub():
    pubsub = RedisPubSub.__new__(RedisPubSub)
    pubsub.redis_client = fakeredis.FakeRedis()
    pubsub.persistent_variables_service = MagicMock()
    pubsub.session_callback_service = SessionCallbackService()
    return pubsub


@pytest.mark.django_db
def test_status_handler_enqueues_on_end(session):
    _register(session)
    _graph_end(session, "done")

    _pubsub().session_status_handler(
        {"data": json.dumps({"session_id": session.pk, "status": "end", "status_data": {}})}
    )

    session.refresh_from_db()
    callback = SessionCallback.objects.get(session=session)
    assert session.status == Session.SessionStatus.END
    assert callback.status == SessionCallback.Status.PENDING
    assert callback.payload["end_node_result"] == "done"
    assert callback.payload["token_usage"]["total_tokens"] == 0


@pytest.mark.django_db
def test_status_handler_run_status_does_not_enqueue(session):
    _register(session)

    _pubsub().session_status_handler(
        {"data": json.dumps({"session_id": session.pk, "status": "run", "status_data": {}})}
    )

    assert SessionCallback.objects.get(session=session).status == SessionCallback.Status.REGISTERED


@pytest.mark.django_db
def test_status_handler_survives_enqueue_failure(session):
    _register(session)
    pubsub = _pubsub()
    pubsub.session_callback_service.enqueue = MagicMock(side_effect=RuntimeError("boom"))

    pubsub.session_status_handler(
        {"data": json.dumps({"session_id": session.pk, "status": "end", "status_data": {}})}
    )

    session.refresh_from_db()
    assert session.status == Session.SessionStatus.END
    assert SessionCallback.objects.get(session=session).status == SessionCallback.Status.REGISTERED
