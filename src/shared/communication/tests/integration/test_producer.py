import json
import uuid

import pytest
import redis as redis_lib

pytestmark = pytest.mark.integration

from communication.brokers.redis_ import RedisPubSubBroker
from communication.message import Message
from communication.producer import Producer
from communication.storages.minio_ import MinioStorage
from communication.storages.redis_ import RedisStorage

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
def minio_storage(minio_params):
    bucket = f"prod-test-{uuid.uuid4().hex[:8]}"
    return MinioStorage(
        host=minio_params["host"],
        port=minio_params["port"],
        access_key=minio_params["access_key"],
        secret_key=minio_params["secret_key"],
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

        received_data = []

        async def subscriber():
            async for data in broker.areceive(channel):
                received_data.append(data)
                return

        task = asyncio.create_task(subscriber())
        await asyncio.sleep(0.2)
        await producer.asend(channel, message)
        await asyncio.wait_for(task, timeout=10)

        assert received_data[0]["id"] == message.id
        assert received_data[0]["payload"] == {"async": "inline"}
        assert "is_used_storage" not in received_data[0]


# ---------------------------------------------------------------------------
# Offload path (broker carries only id; payload in MinIO)
# ---------------------------------------------------------------------------


class TestOffloadPath:
    def test_large_payload_stored_in_minio(self, broker, minio_storage, redis_url):
        """Large payload must be stored in MinIO; broker carries only the id."""
        channel = _unique_channel()
        producer = Producer(
            broker, minio_storage, payload_size_threshold=SMALL_THRESHOLD
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

        # Payload stored verbatim in MinIO.
        stored = minio_storage.get(message.id)
        assert stored is not None
        assert json.loads(stored) == big_payload

    @pytest.mark.asyncio
    async def test_async_large_payload_stored_in_minio(
        self, broker, minio_storage, redis_url
    ):
        import asyncio

        channel = _unique_channel()
        producer = Producer(
            broker, minio_storage, payload_size_threshold=SMALL_THRESHOLD
        )
        big_payload = {"data": "Y" * (SMALL_THRESHOLD + 100)}
        message = Message(payload=big_payload)

        received_data = []

        async def subscriber():
            async for data in broker.areceive(channel):
                received_data.append(data)
                return

        task = asyncio.create_task(subscriber())
        await asyncio.sleep(0.2)
        await producer.asend(channel, message)
        await asyncio.wait_for(task, timeout=10)

        broker_data = received_data[0]
        assert broker_data == {"id": message.id, "is_used_storage": True}

        stored = await minio_storage.aget(message.id)
        assert stored is not None
        assert json.loads(stored) == big_payload
