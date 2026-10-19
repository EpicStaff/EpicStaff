"""
Tests for the shared Redis Streams client publish path, against fakeredis.
"""

import fakeredis
import pytest
import pytest_asyncio
import redis.asyncio as aioredis

from src.shared.redis_streams import RedisStreamClient


@pytest_asyncio.fixture
async def stream_client(monkeypatch):
    fake_redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    monkeypatch.setattr(aioredis, "from_url", lambda url, **kwargs: fake_redis)
    client = RedisStreamClient(host="localhost", port=6379)
    await client.connect()
    yield client, fake_redis
    await client.close()


@pytest.mark.asyncio
async def test_publish_with_ttl_sets_expiry_on_stream(stream_client):
    client, fake_redis = stream_client

    message_id = await client.publish(
        "agent.results:run-a", {"type": "agent.result"}, maxlen=None, ttl_s=3600
    )

    entries = await fake_redis.xrange("agent.results:run-a")
    assert entries == [(message_id, {"type": "agent.result"})]
    assert 0 < await fake_redis.ttl("agent.results:run-a") <= 3600


@pytest.mark.asyncio
async def test_publish_with_ttl_refreshes_expiry_on_every_publish(stream_client):
    client, fake_redis = stream_client
    await client.publish("agent.results:run-a", {"n": "1"}, ttl_s=3600)
    await fake_redis.expire("agent.results:run-a", 5)

    await client.publish("agent.results:run-a", {"n": "2"}, ttl_s=3600)

    assert await fake_redis.ttl("agent.results:run-a") > 5
    assert await fake_redis.xlen("agent.results:run-a") == 2


@pytest.mark.asyncio
async def test_publish_with_ttl_recreates_deleted_stream_with_expiry(stream_client):
    client, fake_redis = stream_client
    await client.publish("agent.results:run-a", {"n": "1"}, ttl_s=3600)
    await fake_redis.delete("agent.results:run-a")

    await client.publish("agent.results:run-a", {"n": "late"}, ttl_s=3600)

    assert await fake_redis.xlen("agent.results:run-a") == 1
    assert 0 < await fake_redis.ttl("agent.results:run-a") <= 3600


@pytest.mark.asyncio
async def test_publish_without_ttl_leaves_stream_persistent(stream_client):
    client, fake_redis = stream_client

    await client.publish("agent.requests", {"type": "agent.run"})

    assert await fake_redis.xlen("agent.requests") == 1
    assert await fake_redis.ttl("agent.requests") == -1
