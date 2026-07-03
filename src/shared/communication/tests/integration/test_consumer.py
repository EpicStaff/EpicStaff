import asyncio
import threading
import time
import uuid

import pytest

pytestmark = pytest.mark.integration

from communication.brokers.redis_ import RedisPubSubBroker
from communication.consumer import Consumer
from communication.message import Message
from communication.producer import Producer
from communication.storages.minio_ import MinioStorage

CHANNEL_PREFIX = "integ-consumer-channel"
SMALL_THRESHOLD = 50
TIMEOUT = 15  # seconds


def _unique_channel(tag: str = "") -> str:
    return f"{CHANNEL_PREFIX}-{tag}-{uuid.uuid4().hex[:8]}"


def _subscribe_and_collect(
    consumer: Consumer, channel: str, count: int
) -> list[Message]:
    """Run consumer.receive in a background thread; return first `count` messages."""
    collected: list[Message] = []
    ready = threading.Event()
    done = threading.Event()

    def run():
        gen = consumer.receive(channel)
        ready.set()
        for msg in gen:
            collected.append(msg)
            if len(collected) >= count:
                done.set()
                return

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    ready.wait(timeout=5)
    return collected, done


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
        """Small message travels inline through the broker and arrives intact."""
        channel = _unique_channel("inline-sync")
        producer = Producer(broker, minio_storage, payload_size_threshold=1024**2)
        consumer = Consumer(broker, minio_storage)
        message = Message(payload={"hello": "world", "num": 42})

        collected, done = _subscribe_and_collect(consumer, channel, 1)
        time.sleep(0.2)  # allow subscription to activate

        producer.send(channel, message)
        done.wait(timeout=TIMEOUT)

        assert len(collected) == 1
        received = collected[0]
        assert received.id == message.id
        assert received.payload == {"hello": "world", "num": 42}

    def test_offloaded_payload_roundtrip_retained_on_early_exit(
        self, broker, minio_storage
    ):
        """Large payload rehydrates correctly AND stays in MinIO when consumer stops early.

        The consumer yields msg1 and returns without advancing to a second message.
        Because storage.remove(msg_id) runs only AFTER the yield resumes, and the
        generator is abandoned before that resumption, the MinIO object must still
        exist — guaranteeing the message can be re-read if processing failed.
        """
        channel = _unique_channel("offload-sync-retain")
        producer = Producer(
            broker, minio_storage, payload_size_threshold=SMALL_THRESHOLD
        )
        consumer = Consumer(broker, minio_storage)
        big_payload = {"data": "Z" * (SMALL_THRESHOLD + 200), "extra": "field"}
        message = Message(payload=big_payload)

        collected, done = _subscribe_and_collect(consumer, channel, 1)
        time.sleep(0.2)

        producer.send(channel, message)
        done.wait(timeout=TIMEOUT)

        assert len(collected) == 1
        received = collected[0]
        assert received.id == message.id
        assert received.payload == big_payload

        # The consumer stopped after yielding msg1 without advancing further.
        # storage.remove() has NOT been called yet — object must still be present.
        assert minio_storage.get(message.id) is not None

    def test_offloaded_payload_removed_on_advance(self, broker, minio_storage):
        """MinIO object for msg1 is removed when the consumer advances past it to msg2.

        Advancing the generator to msg2 resumes execution after msg1's yield, which
        is exactly where storage.remove(msg1_id) runs.  msg2's object is retained
        because the consumer stops after collecting it without advancing further.
        """
        channel = _unique_channel("offload-sync-advance")
        producer = Producer(
            broker, minio_storage, payload_size_threshold=SMALL_THRESHOLD
        )
        consumer = Consumer(broker, minio_storage)
        payload1 = {"data": "Z" * (SMALL_THRESHOLD + 200), "seq": 1}
        payload2 = {"data": "Y" * (SMALL_THRESHOLD + 200), "seq": 2}
        msg1 = Message(payload=payload1)
        msg2 = Message(payload=payload2)

        # Collect 2 messages: advancing from msg1 to msg2 triggers remove(msg1_id).
        collected, done = _subscribe_and_collect(consumer, channel, 2)
        time.sleep(0.2)

        producer.send(channel, msg1)
        producer.send(channel, msg2)
        done.wait(timeout=TIMEOUT)

        assert len(collected) == 2
        assert collected[0].payload == payload1
        assert collected[1].payload == payload2

        # Advancing past msg1 triggered remove — its MinIO object is gone.
        assert minio_storage.get(msg1.id) is None
        # msg2 was the last collected; the generator was abandoned after it.
        # remove(msg2_id) never ran — object is still present.
        assert minio_storage.get(msg2.id) is not None

    def test_mixed_messages_both_arrive(self, broker, minio_storage):
        """One inline + one offloaded message: both arrive with correct payloads."""
        channel = _unique_channel("mixed-sync")
        producer = Producer(
            broker, minio_storage, payload_size_threshold=SMALL_THRESHOLD
        )
        consumer = Consumer(broker, minio_storage)

        small_msg = Message(payload={"size": "small"})
        large_msg = Message(payload={"data": "A" * (SMALL_THRESHOLD + 100)})

        collected, done = _subscribe_and_collect(consumer, channel, 2)
        time.sleep(0.2)

        producer.send(channel, small_msg)
        producer.send(channel, large_msg)
        done.wait(timeout=TIMEOUT)

        assert len(collected) == 2
        by_id = {m.id: m for m in collected}

        assert by_id[small_msg.id].payload == {"size": "small"}
        assert by_id[large_msg.id].payload == {"data": "A" * (SMALL_THRESHOLD + 100)}


class TestAsyncEndToEnd:
    @pytest.mark.asyncio
    async def test_async_inline_payload_roundtrip(self, broker, minio_storage):
        channel = _unique_channel("inline-async")
        producer = Producer(broker, minio_storage, payload_size_threshold=1024**2)
        consumer = Consumer(broker, minio_storage)
        message = Message(payload={"async": True, "value": 99})

        collected: list[Message] = []

        async def subscriber():
            async for msg in consumer.areceive(channel):
                collected.append(msg)
                return

        task = asyncio.create_task(subscriber())
        await asyncio.sleep(0.2)
        await producer.asend(channel, message)
        await asyncio.wait_for(task, timeout=TIMEOUT)

        assert len(collected) == 1
        assert collected[0].id == message.id
        assert collected[0].payload == {"async": True, "value": 99}

    @pytest.mark.asyncio
    async def test_async_offloaded_payload_roundtrip_retained_on_early_exit(
        self, broker, minio_storage
    ):
        """Large payload rehydrates correctly AND stays in MinIO when async consumer stops early.

        The consumer yields msg1 and returns without advancing to a second message.
        aremove(msg_id) runs only after the yield resumes, so when the async for loop
        exits early the object is deliberately retained for replay safety.
        """
        channel = _unique_channel("offload-async-retain")
        producer = Producer(
            broker, minio_storage, payload_size_threshold=SMALL_THRESHOLD
        )
        consumer = Consumer(broker, minio_storage)
        big_payload = {"data": "B" * (SMALL_THRESHOLD + 200)}
        message = Message(payload=big_payload)

        collected: list[Message] = []

        async def subscriber():
            async for msg in consumer.areceive(channel):
                collected.append(msg)
                return  # stop without advancing — aremove never runs

        task = asyncio.create_task(subscriber())
        await asyncio.sleep(0.2)
        await producer.asend(channel, message)
        await asyncio.wait_for(task, timeout=TIMEOUT)

        assert len(collected) == 1
        assert collected[0].id == message.id
        assert collected[0].payload == big_payload

        # Generator was abandoned after the first yield — object must still exist.
        assert await minio_storage.aget(message.id) is not None

    @pytest.mark.asyncio
    async def test_async_offloaded_payload_removed_on_advance(
        self, broker, minio_storage
    ):
        """MinIO object for msg1 is removed when the async consumer advances past it to msg2.

        When the async for loop resumes after yielding msg1 to receive msg2, the code
        after the yield runs and calls aremove(msg1_id).  msg2's object remains because
        the consumer exits before advancing again.
        """
        channel = _unique_channel("offload-async-advance")
        producer = Producer(
            broker, minio_storage, payload_size_threshold=SMALL_THRESHOLD
        )
        consumer = Consumer(broker, minio_storage)
        payload1 = {"data": "B" * (SMALL_THRESHOLD + 200), "seq": 1}
        payload2 = {"data": "A" * (SMALL_THRESHOLD + 200), "seq": 2}
        msg1 = Message(payload=payload1)
        msg2 = Message(payload=payload2)

        collected: list[Message] = []

        async def subscriber():
            async for msg in consumer.areceive(channel):
                collected.append(msg)
                if len(collected) >= 2:
                    return  # stop after msg2; aremove(msg2_id) never runs

        task = asyncio.create_task(subscriber())
        await asyncio.sleep(0.2)
        await producer.asend(channel, msg1)
        await producer.asend(channel, msg2)

        try:
            await asyncio.wait_for(task, timeout=TIMEOUT)
        except asyncio.TimeoutError:
            task.cancel()
            pytest.fail("Did not receive both messages within timeout")

        assert len(collected) == 2
        assert collected[0].payload == payload1
        assert collected[1].payload == payload2

        # Advancing from msg1 to msg2 triggered aremove(msg1_id) — object gone.
        assert await minio_storage.aget(msg1.id) is None
        # Consumer stopped after msg2 without advancing — msg2's object is retained.
        assert await minio_storage.aget(msg2.id) is not None

    @pytest.mark.asyncio
    async def test_async_mixed_messages_both_arrive(self, broker, minio_storage):
        channel = _unique_channel("mixed-async")
        producer = Producer(
            broker, minio_storage, payload_size_threshold=SMALL_THRESHOLD
        )
        consumer = Consumer(broker, minio_storage)

        small_msg = Message(payload={"size": "async-small"})
        large_msg = Message(payload={"data": "C" * (SMALL_THRESHOLD + 100)})

        collected: list[Message] = []

        async def subscriber():
            async for msg in consumer.areceive(channel):
                collected.append(msg)
                if len(collected) >= 2:
                    return

        task = asyncio.create_task(subscriber())
        await asyncio.sleep(0.2)
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
