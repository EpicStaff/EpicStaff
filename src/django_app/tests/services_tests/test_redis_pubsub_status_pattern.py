import json

import fakeredis
import pytest

from tables.models.graph_models import Graph
from tables.models.session_models import Session
from tables.services import redis_pubsub


@pytest.fixture
def fake_server():
    yield fakeredis.FakeServer()


@pytest.fixture
def listener(monkeypatch, fake_server):
    # A new client per call, like the real factory, so _reconnect() gets a fresh connection.
    monkeypatch.setattr(
        redis_pubsub.RedisPubSub,
        "_create_redis_client",
        lambda self: fakeredis.FakeRedis(server=fake_server, decode_responses=True),
    )
    # close_old_connections() would drop the test's transactional DB connection.
    monkeypatch.setattr(redis_pubsub, "close_old_connections", lambda: None)
    monkeypatch.setattr(redis_pubsub, "start_periodic_malloc_trim", lambda: None)
    # The worker registers its handlers, then loops forever; stop it after registration.
    monkeypatch.setattr(
        redis_pubsub.RedisPubSub, "_run_with_reconnect", lambda self, label, inner_loop: None
    )
    listener = redis_pubsub.RedisPubSub()
    listener.listen_for_redis_messages_worker()
    yield listener
    listener.pubsub.close()


@pytest.fixture
def publisher(fake_server):
    client = fakeredis.FakeRedis(server=fake_server, decode_responses=True)
    yield client
    client.close()


@pytest.fixture
def running_session(default_org):
    graph = Graph.objects.create(name="status-pattern", org=default_org)
    yield Session.objects.create(
        graph=graph, status=Session.SessionStatus.RUN, variables={}
    )


def _status_payload(session_id, status):
    return json.dumps({"session_id": session_id, "status": status, "status_data": {}})


def _deliver_pending(listener):
    # Each call reads at most one message; subscribe acknowledgements are reads too.
    for _ in range(10):
        listener.listen_for_messages()


@pytest.mark.django_db
def test_status_on_the_sessions_status_channel_updates_the_session(
    listener, publisher, running_session
):
    listener.subscribe_to_channels()

    publisher.publish(
        f"session:update:{running_session.id}:status",
        _status_payload(running_session.id, Session.SessionStatus.ERROR),
    )
    _deliver_pending(listener)

    running_session.refresh_from_db()
    assert running_session.status == Session.SessionStatus.ERROR
    assert running_session.finished_at is not None


@pytest.mark.django_db
def test_message_on_the_sessions_messages_channel_does_not_reach_the_status_handler(
    listener, publisher, running_session
):
    listener.subscribe_to_channels()

    publisher.publish(
        f"session:update:{running_session.id}:messages",
        _status_payload(running_session.id, Session.SessionStatus.ERROR),
    )
    _deliver_pending(listener)

    running_session.refresh_from_db()
    assert running_session.status == Session.SessionStatus.RUN


@pytest.mark.django_db
def test_pattern_still_delivers_after_a_reconnect(listener, publisher, running_session):
    listener.subscribe_to_channels()
    listener._reconnect()
    listener.subscribe_to_channels()

    publisher.publish(
        f"session:update:{running_session.id}:status",
        _status_payload(running_session.id, Session.SessionStatus.STOP),
    )
    _deliver_pending(listener)

    running_session.refresh_from_db()
    assert running_session.status == Session.SessionStatus.STOP
