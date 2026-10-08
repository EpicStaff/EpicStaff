import json

import fakeredis
import pytest

from services.redis_service import RedisService
from settings import GRAPH_MESSAGE_STREAM_MAXLEN
from utils.singleton_meta import SingletonMeta


@pytest.fixture
def redis_service_with_fake_redis():
    SingletonMeta._instances.pop(RedisService, None)
    server = fakeredis.FakeServer()
    redis_service = RedisService(
        host="127.0.0.1", port=6379, user="default", password="redis_password"
    )
    # One server behind both clients, as in production: they share one Redis.
    redis_service.aioredis_client = fakeredis.FakeAsyncRedis(
        server=server, decode_responses=True
    )
    redis_service.sync_redis_client = fakeredis.FakeRedis(server=server, decode_responses=True)
    yield redis_service, redis_service.sync_redis_client
    SingletonMeta._instances.pop(RedisService, None)


def _message(uuid: str, text: str = "hello") -> dict:
    return {
        "session_id": 7,
        "name": "Agent ✓",
        "execution_order": 3,
        "timestamp": "2026-10-05T10:00:00+00:00",
        "message_data": {"message_type": "finish", "output": {"text": text}},
        "uuid": uuid,
    }


@pytest.mark.asyncio
async def test_graph_message_is_appended_to_the_stream_as_an_envelope(
    redis_service_with_fake_redis,
):
    redis_service, redis_client = redis_service_with_fake_redis
    message = _message("uuid-1")

    await redis_service.aadd_graph_message(message)

    # The literal stream name and field names are the contract django_app reads.
    [(_entry_id, fields)] = redis_client.xrange("graph.messages")
    assert fields["type"] == "graph.message"
    assert fields["correlation_id"] == "uuid-1"
    assert json.loads(fields["payload"]) == message


@pytest.mark.asyncio
async def test_sync_and_async_appends_keep_their_order_in_one_stream(
    redis_service_with_fake_redis,
):
    redis_service, redis_client = redis_service_with_fake_redis

    await redis_service.aadd_graph_message(_message("uuid-1"))
    redis_service.add_graph_message(_message("uuid-2"))
    await redis_service.aadd_graph_message(_message("uuid-3"))

    entries = redis_client.xrange("graph.messages")
    assert [fields["correlation_id"] for _entry_id, fields in entries] == [
        "uuid-1",
        "uuid-2",
        "uuid-3",
    ]


@pytest.mark.asyncio
async def test_stream_is_capped_so_an_absent_reader_cannot_fill_redis(
    redis_service_with_fake_redis,
):
    redis_service, redis_client = redis_service_with_fake_redis

    for index in range(GRAPH_MESSAGE_STREAM_MAXLEN + 500):
        await redis_service.aadd_graph_message(_message(f"uuid-{index}", text=""))

    # Approximate trimming removes whole nodes, so a few extra entries may remain.
    assert redis_client.xlen("graph.messages") < GRAPH_MESSAGE_STREAM_MAXLEN + 500
    assert redis_client.xlen("graph.messages") >= GRAPH_MESSAGE_STREAM_MAXLEN
