import json

import fakeredis
import pytest

from tables.services.redis_service import RedisService


@pytest.fixture
def redis_service_with_fake_redis(monkeypatch):
    redis_client = fakeredis.FakeRedis(decode_responses=True)
    redis_service = RedisService()
    monkeypatch.setattr(redis_service, "_redis_client", redis_client)
    yield redis_service, redis_client
    redis_client.close()


def _published(pubsub) -> list[dict]:
    # Subscribe acknowledgements are read too: with ignore_subscribe_messages,
    # get_message() returns None for them and the loop would stop early.
    messages = []
    while (message := pubsub.get_message(timeout=0.05)) is not None:
        if message["type"] == "message":
            messages.append(message)
    return messages


def test_user_graph_message_is_published_whole_only_to_its_session(
    redis_service_with_fake_redis,
):
    redis_service, redis_client = redis_service_with_fake_redis
    subscriber = redis_client.pubsub()
    subscriber.subscribe("session:update:11:messages", "session:update:12:messages")
    data = {"session_id": 11, "uuid": "user-message-uuid", "message_data": {"message_type": "user"}}

    redis_service.publish_user_graph_message(11, data)

    messages = _published(subscriber)
    subscriber.close()
    assert [message["channel"] for message in messages] == ["session:update:11:messages"]
    assert json.loads(messages[0]["data"]) == data
    assert redis_client.keys("*") == []


def test_user_graph_message_file_data_is_published_as_a_preview(redis_service_with_fake_redis):
    redis_service, redis_client = redis_service_with_fake_redis
    subscriber = redis_client.pubsub()
    subscriber.subscribe("session:update:11:messages")
    data = {
        "session_id": 11,
        "uuid": "user-message-uuid",
        "message_data": {"message_type": "user", "files": [{"base64_data": "B" * 500}]},
    }

    redis_service.publish_user_graph_message(11, data)

    messages = _published(subscriber)
    subscriber.close()
    assert json.loads(messages[0]["data"])["message_data"]["files"] == [{"base64_data": "B" * 50}]
    assert data["message_data"]["files"][0]["base64_data"] == "B" * 500
