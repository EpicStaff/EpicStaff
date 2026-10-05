import json

import fakeredis
import pytest
from django.conf import settings

from tables.models.graph_models import Graph
from tables.models.session_models import Session
from tables.services import redis_pubsub


@pytest.fixture
def pubsub_with_redis(monkeypatch):
    redis_client = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(
        redis_pubsub.RedisPubSub, "_create_redis_client", lambda self: redis_client
    )
    # close_old_connections() would drop the test's transactional DB connection.
    monkeypatch.setattr(redis_pubsub, "close_old_connections", lambda: None)
    yield redis_pubsub.RedisPubSub(), redis_client


@pytest.mark.django_db
def test_graph_message_is_cached_as_the_received_string(default_org, pubsub_with_redis):
    pubsub, redis_client = pubsub_with_redis
    graph = Graph.objects.create(name="graph-messages", org=default_org)
    session = Session.objects.create(
        graph=graph, status=Session.SessionStatus.RUN, variables={}
    )
    # Compact separators and a non-ASCII character: json.dumps() with defaults would
    # produce a different string, so an exact match proves no re-serialisation.
    received = json.dumps(
        {
            "session_id": session.id,
            "name": "Agent ✓",
            "execution_order": 1,
            "timestamp": "2026-10-05T10:00:00",
            "message_data": {"message_type": "agent", "text": "x" * 1024},
            "uuid": "message-uuid-1",
        },
        separators=(",", ":"),
        ensure_ascii=False,
    )

    pubsub.graph_session_message_handler({"data": received})

    assert redis_client.get(f"graph:message:{session.id}:message-uuid-1") == received
    assert 0 < redis_client.ttl(f"graph:message:{session.id}:message-uuid-1") <= 60
    buffered = list(pubsub.buffers[settings.GRAPH_MESSAGES_CHANNEL])
    assert [message["uuid"] for message in buffered] == ["message-uuid-1"]


def _published(pubsub) -> list[dict]:
    # Subscribe acknowledgements are read too: with ignore_subscribe_messages,
    # get_message() returns None for them and the loop would stop early.
    messages = []
    while (message := pubsub.get_message(timeout=0.05)) is not None:
        if message["type"] == "message":
            messages.append(message)
    return messages


@pytest.mark.django_db
def test_graph_message_pointer_is_published_only_on_the_sessions_messages_channel(
    default_org, pubsub_with_redis
):
    pubsub, redis_client = pubsub_with_redis
    graph = Graph.objects.create(name="graph-messages", org=default_org)
    session = Session.objects.create(
        graph=graph, status=Session.SessionStatus.RUN, variables={}
    )
    other_session = Session.objects.create(
        graph=graph, status=Session.SessionStatus.RUN, variables={}
    )
    subscriber = redis_client.pubsub()
    subscriber.subscribe(
        f"session:update:{session.id}:messages",
        f"session:update:{other_session.id}:messages",
    )
    received = json.dumps(
        {
            "session_id": session.id,
            "name": "Agent",
            "execution_order": 1,
            "timestamp": "2026-10-05T10:00:00",
            "message_data": {"message_type": "agent"},
            "uuid": "message-uuid-2",
        }
    )

    pubsub.graph_session_message_handler({"data": received})

    messages = _published(subscriber)
    subscriber.close()
    assert [message["channel"] for message in messages] == [
        f"session:update:{session.id}:messages"
    ]
    assert json.loads(messages[0]["data"]) == {
        "uuid": "message-uuid-2",
        "session_id": session.id,
    }
