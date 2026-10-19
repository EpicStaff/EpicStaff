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
    # The sync client only reads back what the async client wrote.
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

    await redis_service.aadd_graph_message(message["uuid"], json.dumps(message))

    # The literal stream name and field names are the contract django_app reads.
    [(_entry_id, fields)] = redis_client.xrange("graph.messages")
    assert fields["type"] == "graph.message"
    assert fields["correlation_id"] == "uuid-1"
    assert json.loads(fields["payload"]) == message


@pytest.mark.asyncio
async def test_stream_is_capped_so_an_absent_reader_cannot_fill_redis(
    redis_service_with_fake_redis,
):
    redis_service, redis_client = redis_service_with_fake_redis

    for index in range(GRAPH_MESSAGE_STREAM_MAXLEN + 500):
        message_uuid = f"uuid-{index}"
        await redis_service.aadd_graph_message(
            message_uuid, json.dumps(_message(message_uuid, text=""))
        )

    # Approximate trimming removes whole nodes, so a few extra entries may remain.
    assert redis_client.xlen("graph.messages") < GRAPH_MESSAGE_STREAM_MAXLEN + 500
    assert redis_client.xlen("graph.messages") >= GRAPH_MESSAGE_STREAM_MAXLEN
