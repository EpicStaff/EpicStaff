import json

import fakeredis
import pytest
from django.db import connection

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


@pytest.fixture
def running_session(default_org):
    graph = Graph.objects.create(name="graph-messages", org=default_org)
    yield Session.objects.create(graph=graph, status=Session.SessionStatus.RUN, variables={})


@pytest.mark.django_db
def test_status_stores_the_token_total_summed_in_the_session_hash(
    pubsub_with_redis, running_session
):
    pubsub, redis_client = pubsub_with_redis
    redis_client.hset(
        f"session:{running_session.id}:token_usage",
        mapping={"total_tokens": 150, "prompt_tokens": 90, "total_cost_usd": "0.002"},
    )

    pubsub.session_status_handler(
        {
            "data": json.dumps(
                {"session_id": running_session.id, "status": "error", "status_data": {}}
            )
        }
    )

    running_session.refresh_from_db()
    expected_total = {
        "total_tokens": 150,
        "prompt_tokens": 90,
        "completion_tokens": 0,
        "successful_requests": 0,
        "cached_prompt_tokens": 0,
        "total_cost_usd": pytest.approx(0.002),
    }
    assert running_session.status == Session.SessionStatus.ERROR
    assert running_session.token_usage == expected_total
    assert running_session.status_data["total_token_usage"] == expected_total


@pytest.mark.django_db
def test_status_of_a_session_without_token_usage_stores_zeros(
    pubsub_with_redis, running_session
):
    pubsub, _redis_client = pubsub_with_redis

    pubsub.session_status_handler(
        {
            "data": json.dumps(
                {"session_id": running_session.id, "status": "run", "status_data": {}}
            )
        }
    )

    running_session.refresh_from_db()
    assert running_session.token_usage["total_tokens"] == 0
    assert running_session.token_usage["total_cost_usd"] == 0


@pytest.mark.django_db
def test_listener_clears_the_query_log_after_a_handler_runs(
    pubsub_with_redis, running_session, settings
):
    settings.DEBUG = True
    pubsub, redis_client = pubsub_with_redis
    handled = []

    def handler_running_a_query(message):
        handled.append(Session.objects.filter(pk=running_session.pk).count())

    pubsub.set_handler("test-channel", handler_running_a_query)
    pubsub.subscribe_to_channels()
    redis_client.publish("test-channel", "payload")

    # The first reads return the subscribe acknowledgement.
    for _ in range(50):
        pubsub.listen_for_messages()
        if handled:
            break
    queries_kept_after_handler = list(connection.queries_log)

    assert handled == [1]
    assert queries_kept_after_handler == []
