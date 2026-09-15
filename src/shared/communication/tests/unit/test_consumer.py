import json

import pytest

from communication.consumer import Consumer
from communication.message import Message
from tests.unit.fakes import FakeBroker, FakeStorage

CHANNEL = "test-channel"


def _consumer(frames, store=None) -> tuple[Consumer, FakeBroker, FakeStorage]:
    broker = FakeBroker(frames=frames)
    storage = FakeStorage(store=store)
    return Consumer(broker, storage), broker, storage


class TestSyncReceiveInline:
    def test_inline_frame_returns_message(self):
        payload = {"key": "value"}
        msg_id = "msg-001"
        consumer, _, _ = _consumer([{"id": msg_id, "payload": payload}])

        message = consumer.receive(CHANNEL)

        assert isinstance(message, Message)
        assert message.id == msg_id
        assert message.payload == payload

    def test_inline_frame_does_not_touch_storage(self):
        consumer, _, storage = _consumer([{"id": "x", "payload": {"a": 1}}])
        consumer.receive(CHANNEL)

        assert storage.gets == []
        assert storage.removes == []

    def test_returns_none_when_no_message(self):
        consumer, _, _ = _consumer(frames=[])
        assert consumer.receive(CHANNEL) is None


class TestSyncReceiveOffloaded:
    def test_offloaded_frame_fetches_from_storage(self):
        payload = {"big": "data"}
        msg_id = "msg-002"
        stored = json.dumps(payload).encode()
        consumer, _, storage = _consumer(
            [{"id": msg_id, "is_used_storage": True}], store={msg_id: stored}
        )

        message = consumer.receive(CHANNEL)

        assert message.payload == payload
        assert msg_id in storage.gets

    def test_offloaded_frame_removed_immediately(self):
        msg_id = "msg-003"
        stored = json.dumps({"x": 1}).encode()
        consumer, _, storage = _consumer(
            [{"id": msg_id, "is_used_storage": True}], store={msg_id: stored}
        )

        consumer.receive(CHANNEL)

        assert msg_id in storage.removes

    def test_offloaded_storage_miss_yields_empty_payload(self):
        msg_id = "msg-004"
        consumer, _, _ = _consumer([{"id": msg_id, "is_used_storage": True}], store={})

        message = consumer.receive(CHANNEL)

        assert message.payload == {}

    def test_is_used_storage_not_in_message(self):
        msg_id = "msg-005"
        stored = json.dumps({"y": 2}).encode()
        consumer, _, _ = _consumer(
            [{"id": msg_id, "is_used_storage": True}], store={msg_id: stored}
        )

        message = consumer.receive(CHANNEL)

        assert "is_used_storage" not in message.model_fields_set


class TestSyncStream:
    def test_stream_yields_messages_in_order(self):
        frames = [
            {"id": "s1", "payload": {"i": 1}},
            {"id": "s2", "payload": {"i": 2}},
            {"id": "s3", "payload": {"i": 3}},
        ]
        consumer, _, _ = _consumer(frames)

        messages = list(consumer.stream(CHANNEL))

        assert [m.id for m in messages] == ["s1", "s2", "s3"]
        assert [m.payload for m in messages] == [{"i": 1}, {"i": 2}, {"i": 3}]

    def test_stream_rehydrates_and_removes_offloaded_payload(self):
        msg_id = "s-off"
        stored = json.dumps({"big": "x"}).encode()
        consumer, _, storage = _consumer(
            [{"id": msg_id, "is_used_storage": True}], store={msg_id: stored}
        )

        messages = list(consumer.stream(CHANNEL))

        assert messages[0].payload == {"big": "x"}
        assert msg_id in storage.gets
        assert msg_id in storage.removes


class TestAsyncReceiveInline:
    @pytest.mark.asyncio
    async def test_inline_frame_returns_message(self):
        payload = {"key": "value"}
        msg_id = "amsg-001"
        consumer, _, _ = _consumer([{"id": msg_id, "payload": payload}])

        message = await consumer.areceive(CHANNEL)

        assert message.id == msg_id
        assert message.payload == payload

    @pytest.mark.asyncio
    async def test_inline_frame_does_not_touch_storage(self):
        consumer, _, storage = _consumer([{"id": "x", "payload": {"a": 1}}])
        await consumer.areceive(CHANNEL)

        assert storage.async_gets == []
        assert storage.async_removes == []

    @pytest.mark.asyncio
    async def test_returns_none_when_no_message(self):
        consumer, _, _ = _consumer(frames=[])
        assert await consumer.areceive(CHANNEL) is None


class TestAsyncReceiveOffloaded:
    @pytest.mark.asyncio
    async def test_offloaded_frame_fetches_and_removes(self):
        payload = {"big": "async-data"}
        msg_id = "amsg-002"
        stored = json.dumps(payload).encode()
        consumer, _, storage = _consumer(
            [{"id": msg_id, "is_used_storage": True}], store={msg_id: stored}
        )

        message = await consumer.areceive(CHANNEL)

        assert message.payload == payload
        assert msg_id in storage.async_gets
        assert msg_id in storage.async_removes

    @pytest.mark.asyncio
    async def test_offloaded_storage_miss_yields_empty_payload(self):
        msg_id = "amsg-004"
        consumer, _, _ = _consumer([{"id": msg_id, "is_used_storage": True}], store={})

        message = await consumer.areceive(CHANNEL)

        assert message.payload == {}


class TestAsyncStream:
    @pytest.mark.asyncio
    async def test_astream_yields_messages_in_order(self):
        frames = [
            {"id": "as1", "payload": {"i": 1}},
            {"id": "as2", "payload": {"i": 2}},
        ]
        consumer, _, _ = _consumer(frames)

        messages = [m async for m in consumer.astream(CHANNEL)]

        assert [m.id for m in messages] == ["as1", "as2"]
        assert [m.payload for m in messages] == [{"i": 1}, {"i": 2}]

    @pytest.mark.asyncio
    async def test_astream_rehydrates_and_removes_offloaded_payload(self):
        msg_id = "as-off"
        stored = json.dumps({"big": "y"}).encode()
        consumer, _, storage = _consumer(
            [{"id": msg_id, "is_used_storage": True}], store={msg_id: stored}
        )

        messages = [m async for m in consumer.astream(CHANNEL)]

        assert messages[0].payload == {"big": "y"}
        assert msg_id in storage.async_gets
        assert msg_id in storage.async_removes
