import json

import fakeredis
import pytest

from services.redis_service import RedisService
from utils.singleton_meta import SingletonMeta


@pytest.fixture
def fake_server():
    yield fakeredis.FakeServer()


@pytest.fixture
def redis_service_with_fake_redis(fake_server):
    SingletonMeta._instances.pop(RedisService, None)
    redis_service = RedisService(
        host="127.0.0.1", port=6379, user="default", password="redis_password"
    )
    redis_service.aioredis_client = fakeredis.FakeAsyncRedis(
        server=fake_server, decode_responses=True
    )
    redis_service.sync_redis_client = fakeredis.FakeRedis(
        server=fake_server, decode_responses=True
    )
    yield redis_service
    SingletonMeta._instances.pop(RedisService, None)


@pytest.fixture
def subscriber(fake_server):
    client = fakeredis.FakeRedis(server=fake_server, decode_responses=True)
    pubsub = client.pubsub()
    yield pubsub
    pubsub.close()
    client.close()


def _published(pubsub) -> list[dict]:
    # Subscribe acknowledgements are read too: with ignore_subscribe_messages,
    # get_message() returns None for them and the loop would stop early.
    messages = []
    while (message := pubsub.get_message(timeout=0.05)) is not None:
        if message["type"] == "message":
            messages.append(message)
    return messages


@pytest.mark.asyncio
async def test_async_status_is_published_on_the_sessions_own_channel(
    redis_service_with_fake_redis, subscriber
):
    subscriber.subscribe("session:update:7:status", "session:update:8:status")

    await redis_service_with_fake_redis.aupdate_session_status(
        session_id=7, status="error", error="node crashed"
    )

    messages = _published(subscriber)
    # The literal channel name is the cross-service contract django_app subscribes to.
    assert [message["channel"] for message in messages] == ["session:update:7:status"]
    assert json.loads(messages[0]["data"]) == {
        "session_id": 7,
        "status": "error",
        "status_data": {"error": "node crashed"},
    }


def test_sync_status_is_published_on_the_sessions_own_channel(
    redis_service_with_fake_redis, subscriber
):
    subscriber.subscribe("session:update:7:status", "session:update:8:status")

    redis_service_with_fake_redis.update_session_status(session_id=7, status="run")

    messages = _published(subscriber)
    assert [message["channel"] for message in messages] == ["session:update:7:status"]
    assert json.loads(messages[0]["data"]) == {
        "session_id": 7,
        "status": "run",
        "status_data": {},
    }


@pytest.mark.asyncio
async def test_another_sessions_subscriber_receives_nothing(
    redis_service_with_fake_redis, subscriber
):
    subscriber.subscribe("session:update:8:status")

    await redis_service_with_fake_redis.aupdate_session_status(session_id=7, status="end")
    redis_service_with_fake_redis.update_session_status(session_id=7, status="end")

    assert _published(subscriber) == []
