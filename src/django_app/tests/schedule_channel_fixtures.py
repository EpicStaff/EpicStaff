"""Fixtures for tests of the schedule channel between Django and the Manager.

Star-imported by the schedule-trigger test modules. Both sides run on fakeredis,
so these tests never publish to a real Redis that live services listen on.
"""

import json
from types import SimpleNamespace

import fakeredis
import pytest
from django.conf import settings

from tables.services import redis_pubsub
from tables.signals import schedule_signals


@pytest.fixture
def manager_channel(monkeypatch):
    """Subscription to what Django publishes for the Manager on the schedule channel."""
    redis_client = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(
        schedule_signals, "RedisService", lambda: SimpleNamespace(redis_client=redis_client)
    )
    subscription = redis_client.pubsub()
    subscription.subscribe(settings.SCHEDULE_CHANNEL)
    # Consume the subscribe confirmation so only published messages remain.
    subscription.get_message(timeout=1)
    yield subscription
    subscription.close()


@pytest.fixture
def schedule_pubsub(monkeypatch):
    """Django's schedule channel handler, as it receives the Manager's signals."""
    monkeypatch.setattr(
        redis_pubsub.RedisPubSub,
        "_create_redis_client",
        lambda self: fakeredis.FakeRedis(decode_responses=True),
    )
    # The handler calls close_old_connections(), which would drop the test's
    # transactional DB connection.
    monkeypatch.setattr(redis_pubsub, "close_old_connections", lambda: None)
    yield redis_pubsub.RedisPubSub()


def published_messages(subscription) -> list[dict]:
    """Return every message already published to the subscription."""
    messages = []
    while (message := subscription.get_message(timeout=0.05)) is not None:
        messages.append(json.loads(message["data"]))
    return messages
