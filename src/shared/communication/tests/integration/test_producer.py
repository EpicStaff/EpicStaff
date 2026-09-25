import json
import uuid

import pytest
import redis as redis_lib

pytestmark = pytest.mark.integration

from communication.brokers.redis_broker import RedisPubSubBroker
from communication.message import Message
from communication.producer import Producer
from communication.storages.s3_storage import S3Storage
from communication.storages.redis_storage import RedisStorage

CHANNEL = "integ-producer-channel"
# Threshold small enough to force offloading with a modest payload.
SMALL_THRESHOLD = 50


def _unique_channel():
    return f"{CHANNEL}-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def broker(redis_url):
    return RedisPubSubBroker(redis_url)


@pytest.fixture
def redis_storage(redis_url):
    return RedisStorage(redis_url, ttl=60)


@pytest.fixture
def s3_storage(s3_params):
    bucket = f"prod-test-{uuid.uuid4().hex[:8]}"
    return S3Storage(
        host=s3_params["host"],
        port=s3_params["port"],
        access_key=s3_params["access_key"],
        secret_key=s3_params["secret_key"],
        bucket=bucket,
        secure=False,
    )


# ---------------------------------------------------------------------------
# Inline path (broker carries full payload)
# ---------------------------------------------------------------------------


class TestInlinePath:
    def test_small_payload_stored_inline_in_broker(
        self, broker, redis_storage, redis_url
    ):
        """A small payload must arrive on the channel as model_dump() without offloading."""
        channel = _unique_channel()
        producer = Producer(broker, redis_storage, payload_size_threshold=1024**2)
        message = Message(payload={"key": "small"})

        # Subscribe BEFORE sending so we don't miss the message.
        raw_client = redis_lib.Redis.from_url(redis_url)
        pubsub = raw_client.pubsub()
        pubsub.subscribe(channel)

        producer.send(channel, message)

        # Drain the subscription confirmation frame, then read the real message.
        raw_frame = None
        for frame in pubsub.listen():
            if frame["type"] == "message":
                raw_frame = frame
                break

        assert raw_frame is not None
        published_data = json.loads(raw_frame["data"])
        assert published_data["id"] == message.id
        assert published_data["payload"] == {"key": "small"}
        assert "is_used_storage" not in published_data

        # Nothing stored in Redis storage.
        assert redis_storage.get(message.id) is None

    @pytest.mark.asyncio
    async def test_async_small_payload_stored_inline(
        self, broker, redis_storage, redis_url
    ):
        """Async send: small payload stays inline."""
        import asyncio

        channel = _unique_channel()
        producer = Producer(broker, redis_storage, payload_size_threshold=1024**2)
        message = Message(payload={"async": "inline"})

        task = asyncio.create_task(broker.areceive(channel, timeout=10))
        await asyncio.sleep(0.2)
        await producer.asend(channel, message)
        data = await asyncio.wait_for(task, timeout=12)

        assert data is not None
        assert data["id"] == message.id
        assert data["payload"] == {"async": "inline"}
        assert "is_used_storage" not in data


# ---------------------------------------------------------------------------
# Offload path (broker carries only id; payload in S3)
# ---------------------------------------------------------------------------


class TestOffloadPath:
    def test_large_payload_stored_in_s3(self, broker, s3_storage, redis_url):
        """Large payload must be stored in S3; broker carries only the id."""
        channel = _unique_channel()
        producer = Producer(
            broker, s3_storage, payload_size_threshold=SMALL_THRESHOLD
        )
        big_payload = {"data": "X" * (SMALL_THRESHOLD + 100)}
        message = Message(payload=big_payload)

        raw_client = redis_lib.Redis.from_url(redis_url)
        pubsub = raw_client.pubsub()
        pubsub.subscribe(channel)

        producer.send(channel, message)

        raw_frame = None
        for frame in pubsub.listen():
            if frame["type"] == "message":
                raw_frame = frame
                break

        assert raw_frame is not None
        broker_data = json.loads(raw_frame["data"])
        assert broker_data == {"id": message.id, "is_used_storage": True}
        assert "payload" not in broker_data

        # Payload stored verbatim in S3.
        stored = s3_storage.get(message.id)
        assert stored is not None
        assert json.loads(stored) == big_payload

    @pytest.mark.asyncio
    async def test_async_large_payload_stored_in_s3(
        self, broker, s3_storage, redis_url
    ):
        import asyncio

        channel = _unique_channel()
        producer = Producer(
            broker, s3_storage, payload_size_threshold=SMALL_THRESHOLD
        )
        big_payload = {"data": "Y" * (SMALL_THRESHOLD + 100)}
        message = Message(payload=big_payload)

        task = asyncio.create_task(broker.areceive(channel, timeout=10))
        await asyncio.sleep(0.2)
        await producer.asend(channel, message)
        broker_data = await asyncio.wait_for(task, timeout=12)

        assert broker_data == {"id": message.id, "is_used_storage": True}

        stored = await s3_storage.aget(message.id)
        assert stored is not None
        assert json.loads(stored) == big_payload
