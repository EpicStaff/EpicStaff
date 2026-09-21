import asyncio
import threading
import time
import uuid

import pytest

pytestmark = pytest.mark.integration

from communication.brokers.redis_broker import RedisPubSubBroker
from communication.consumer import Consumer
from communication.message import Message
from communication.producer import Producer
from communication.storages.minio_storage import MinioStorage

CHANNEL_PREFIX = "integ-consumer-channel"
SMALL_THRESHOLD = 50
TIMEOUT = 15  # seconds
GRACE = 0.5  # let the subscription activate before publishing


def _unique_channel(tag: str = "") -> str:
    return f"{CHANNEL_PREFIX}-{tag}-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def broker(redis_url):
    return RedisPubSubBroker(redis_url)


@pytest.fixture
def minio_storage(minio_params):
    bucket = f"cons-test-{uuid.uuid4().hex[:8]}"
    return MinioStorage(
        host=minio_params["host"],
        port=minio_params["port"],
        access_key=minio_params["access_key"],
        secret_key=minio_params["secret_key"],
        bucket=bucket,
        secure=False,
    )


class TestSyncEndToEnd:
    def test_inline_payload_roundtrip(self, broker, minio_storage):
        channel = _unique_channel("inline-sync")
        producer = Producer(broker, minio_storage, payload_size_threshold=1024**2)
        consumer = Consumer(broker, minio_storage)
        message = Message(payload={"hello": "world", "num": 42})

        holder: list = []

        def subscriber():
            holder.append(consumer.receive(channel, timeout=TIMEOUT))

        thread = threading.Thread(target=subscriber, daemon=True)
        thread.start()
        time.sleep(GRACE)
        producer.send(channel, message)
        thread.join(timeout=TIMEOUT + 2)

        assert len(holder) == 1
        received = holder[0]
        assert received is not None
        assert received.id == message.id
        assert received.payload == {"hello": "world", "num": 42}

    def test_offloaded_payload_roundtrip_and_removed(self, broker, minio_storage):
        """Large payload rehydrates from MinIO and is removed immediately on receipt."""
        channel = _unique_channel("offload-sync")
        producer = Producer(
            broker, minio_storage, payload_size_threshold=SMALL_THRESHOLD
        )
        consumer = Consumer(broker, minio_storage)
        big_payload = {"data": "Z" * (SMALL_THRESHOLD + 200)}
        message = Message(payload=big_payload)

        holder: list = []

        def subscriber():
            holder.append(consumer.receive(channel, timeout=TIMEOUT))

        thread = threading.Thread(target=subscriber, daemon=True)
        thread.start()
        time.sleep(GRACE)
        producer.send(channel, message)
        thread.join(timeout=TIMEOUT + 2)

        assert len(holder) == 1
        received = holder[0]
        assert received is not None
        assert received.id == message.id
        assert received.payload == big_payload
        # New behavior: the offloaded object is removed immediately on receipt.
        assert minio_storage.get(message.id) is None

    def test_stream_collects_multiple_mixed_messages(self, broker, minio_storage):
        channel = _unique_channel("mixed-sync")
        producer = Producer(
            broker, minio_storage, payload_size_threshold=SMALL_THRESHOLD
        )
        consumer = Consumer(broker, minio_storage)
        small_msg = Message(payload={"size": "small"})
        large_msg = Message(payload={"data": "A" * (SMALL_THRESHOLD + 100)})

        collected: list[Message] = []

        def subscriber():
            for msg in consumer.stream(channel):
                collected.append(msg)
                if len(collected) >= 2:
                    break

        thread = threading.Thread(target=subscriber, daemon=True)
        thread.start()
        time.sleep(GRACE)
        producer.send(channel, small_msg)
        producer.send(channel, large_msg)
        thread.join(timeout=TIMEOUT)

        assert len(collected) == 2
        by_id = {m.id: m for m in collected}
        assert by_id[small_msg.id].payload == {"size": "small"}
        assert by_id[large_msg.id].payload == {"data": "A" * (SMALL_THRESHOLD + 100)}
        # The offloaded large message was rehydrated then removed from storage.
        assert minio_storage.get(large_msg.id) is None


class TestAsyncEndToEnd:
    @pytest.mark.asyncio
    async def test_async_inline_payload_roundtrip(self, broker, minio_storage):
        channel = _unique_channel("inline-async")
        producer = Producer(broker, minio_storage, payload_size_threshold=1024**2)
        consumer = Consumer(broker, minio_storage)
        message = Message(payload={"async": True, "value": 99})

        task = asyncio.create_task(consumer.areceive(channel, timeout=TIMEOUT))
        await asyncio.sleep(GRACE)
        await producer.asend(channel, message)
        received = await asyncio.wait_for(task, timeout=TIMEOUT + 2)

        assert received is not None
        assert received.id == message.id
        assert received.payload == {"async": True, "value": 99}

    @pytest.mark.asyncio
    async def test_async_offloaded_payload_roundtrip_and_removed(
        self, broker, minio_storage
    ):
        channel = _unique_channel("offload-async")
        producer = Producer(
            broker, minio_storage, payload_size_threshold=SMALL_THRESHOLD
        )
        consumer = Consumer(broker, minio_storage)
        big_payload = {"data": "B" * (SMALL_THRESHOLD + 200)}
        message = Message(payload=big_payload)

        task = asyncio.create_task(consumer.areceive(channel, timeout=TIMEOUT))
        await asyncio.sleep(GRACE)
        await producer.asend(channel, message)
        received = await asyncio.wait_for(task, timeout=TIMEOUT + 2)

        assert received is not None
        assert received.id == message.id
        assert received.payload == big_payload
        assert await minio_storage.aget(message.id) is None

    @pytest.mark.asyncio
    async def test_async_stream_collects_multiple_mixed_messages(
        self, broker, minio_storage
    ):
        channel = _unique_channel("mixed-async")
        producer = Producer(
            broker, minio_storage, payload_size_threshold=SMALL_THRESHOLD
        )
        consumer = Consumer(broker, minio_storage)
        small_msg = Message(payload={"size": "async-small"})
        large_msg = Message(payload={"data": "C" * (SMALL_THRESHOLD + 100)})

        collected: list[Message] = []

        async def subscriber():
            async for msg in consumer.astream(channel):
                collected.append(msg)
                if len(collected) >= 2:
                    return

        task = asyncio.create_task(subscriber())
        await asyncio.sleep(GRACE)
        await producer.asend(channel, small_msg)
        await producer.asend(channel, large_msg)
        try:
            await asyncio.wait_for(task, timeout=TIMEOUT)
        except asyncio.TimeoutError:
            task.cancel()
            pytest.fail("Did not receive both messages within timeout")

        assert len(collected) == 2
        by_id = {m.id: m for m in collected}
        assert by_id[small_msg.id].payload == {"size": "async-small"}
        assert by_id[large_msg.id].payload == {"data": "C" * (SMALL_THRESHOLD + 100)}
        assert await minio_storage.aget(large_msg.id) is None
