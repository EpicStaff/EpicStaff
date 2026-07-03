import json

import pytest

from communication.message import Message
from communication.producer import Producer
from tests.unit.fakes import FakeBroker, FakeStorage

CHANNEL = "test-channel"
# Tiny threshold so we can trigger offloading without huge allocations.
SMALL_THRESHOLD = 50


def _producer(
    threshold: int = SMALL_THRESHOLD,
) -> tuple[Producer, FakeBroker, FakeStorage]:
    broker = FakeBroker()
    storage = FakeStorage()
    producer = Producer(broker, storage, payload_size_threshold=threshold)
    return producer, broker, storage


class TestSyncSendInline:
    def test_small_payload_goes_inline(self):
        producer, broker, storage = _producer()
        message = Message(payload={"a": 1})
        producer.send(CHANNEL, message)

        assert len(broker.sent) == 1
        channel, data = broker.sent[0]
        assert channel == CHANNEL
        assert data == message.model_dump()
        assert "payload" in data
        assert "is_used_storage" not in data
        assert len(storage.puts) == 0

    def test_inline_data_contains_id_and_payload(self):
        producer, broker, storage = _producer()
        message = Message(payload={"x": 42})
        producer.send(CHANNEL, message)

        _, data = broker.sent[0]
        assert data["id"] == message.id
        assert data["payload"] == {"x": 42}


class TestSyncSendOffload:
    def test_large_payload_offloads_to_storage(self):
        producer, broker, storage = _producer()
        big_payload = {"data": "y" * (SMALL_THRESHOLD + 10)}
        message = Message(payload=big_payload)
        producer.send(CHANNEL, message)

        assert len(storage.puts) == 1
        stored_key, stored_bytes = storage.puts[0]
        assert stored_key == message.id
        assert stored_bytes == json.dumps(big_payload).encode()

        assert len(broker.sent) == 1
        _, data = broker.sent[0]
        assert data == {"id": message.id, "is_used_storage": True}
        assert "payload" not in data

    def test_offloaded_data_has_no_inline_payload(self):
        producer, broker, storage = _producer()
        message = Message(payload={"data": "z" * (SMALL_THRESHOLD + 1)})
        producer.send(CHANNEL, message)

        _, data = broker.sent[0]
        assert "payload" not in data


class TestSyncSendBoundary:
    def test_exact_threshold_stays_inline(self):
        """Payload whose encoded size equals the threshold is not offloaded."""
        payload = {"k": "v"}
        raw = json.dumps(payload).encode()
        threshold = len(raw)
        producer, broker, storage = _producer(threshold=threshold)
        message = Message(payload=payload)
        producer.send(CHANNEL, message)

        assert len(storage.puts) == 0
        _, data = broker.sent[0]
        assert data["payload"] == payload

    def test_one_byte_over_threshold_offloads(self):
        payload = {"k": "v"}
        raw = json.dumps(payload).encode()
        threshold = len(raw) - 1  # one byte under the payload, so payload exceeds it
        producer, broker, storage = _producer(threshold=threshold)
        message = Message(payload=payload)
        producer.send(CHANNEL, message)

        assert len(storage.puts) == 1
        _, data = broker.sent[0]
        assert "is_used_storage" in data


class TestAsyncSendInline:
    @pytest.mark.asyncio
    async def test_small_payload_goes_inline(self):
        producer, broker, storage = _producer()
        message = Message(payload={"a": 1})
        await producer.asend(CHANNEL, message)

        assert len(broker.async_sent) == 1
        channel, data = broker.async_sent[0]
        assert channel == CHANNEL
        assert data == message.model_dump()
        assert "is_used_storage" not in data
        assert len(storage.async_puts) == 0

    @pytest.mark.asyncio
    async def test_inline_data_contains_id_and_payload(self):
        producer, broker, storage = _producer()
        message = Message(payload={"x": 42})
        await producer.asend(CHANNEL, message)

        _, data = broker.async_sent[0]
        assert data["id"] == message.id
        assert data["payload"] == {"x": 42}


class TestAsyncSendOffload:
    @pytest.mark.asyncio
    async def test_large_payload_offloads_to_storage(self):
        producer, broker, storage = _producer()
        big_payload = {"data": "y" * (SMALL_THRESHOLD + 10)}
        message = Message(payload=big_payload)
        await producer.asend(CHANNEL, message)

        assert len(storage.async_puts) == 1
        stored_key, stored_bytes = storage.async_puts[0]
        assert stored_key == message.id
        assert stored_bytes == json.dumps(big_payload).encode()

        _, data = broker.async_sent[0]
        assert data == {"id": message.id, "is_used_storage": True}

    @pytest.mark.asyncio
    async def test_offloaded_data_has_no_inline_payload(self):
        producer, broker, storage = _producer()
        message = Message(payload={"data": "z" * (SMALL_THRESHOLD + 1)})
        await producer.asend(CHANNEL, message)

        _, data = broker.async_sent[0]
        assert "payload" not in data


class TestAsyncSendBoundary:
    @pytest.mark.asyncio
    async def test_exact_threshold_stays_inline(self):
        payload = {"k": "v"}
        raw = json.dumps(payload).encode()
        threshold = len(raw)
        producer, broker, storage = _producer(threshold=threshold)
        message = Message(payload=payload)
        await producer.asend(CHANNEL, message)

        assert len(storage.async_puts) == 0
        _, data = broker.async_sent[0]
        assert data["payload"] == payload

    @pytest.mark.asyncio
    async def test_one_byte_over_threshold_offloads(self):
        payload = {"k": "v"}
        raw = json.dumps(payload).encode()
        threshold = len(raw) - 1
        producer, broker, storage = _producer(threshold=threshold)
        message = Message(payload=payload)
        await producer.asend(CHANNEL, message)

        assert len(storage.async_puts) == 1
        _, data = broker.async_sent[0]
        assert "is_used_storage" in data
