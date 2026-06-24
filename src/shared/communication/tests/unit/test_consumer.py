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
    def test_inline_frame_yields_message(self):
        payload = {"key": "value"}
        msg_id = "msg-001"
        frames = [{"id": msg_id, "payload": payload}]
        consumer, broker, storage = _consumer(frames)

        messages = list(consumer.receive(CHANNEL))

        assert len(messages) == 1
        assert isinstance(messages[0], Message)
        assert messages[0].id == msg_id
        assert messages[0].payload == payload

    def test_inline_frame_does_not_call_storage_get(self):
        frames = [{"id": "x", "payload": {"a": 1}}]
        consumer, _, storage = _consumer(frames)
        list(consumer.receive(CHANNEL))

        assert len(storage.gets) == 0

    def test_inline_frame_does_not_call_storage_remove(self):
        frames = [{"id": "x", "payload": {"a": 1}}]
        consumer, _, storage = _consumer(frames)
        list(consumer.receive(CHANNEL))

        assert len(storage.removes) == 0


class TestSyncReceiveOffloaded:
    def test_offloaded_frame_fetches_from_storage(self):
        payload = {"big": "data"}
        msg_id = "msg-002"
        stored_bytes = json.dumps(payload).encode()
        frames = [{"id": msg_id, "is_used_storage": True}]
        consumer, _, storage = _consumer(frames, store={msg_id: stored_bytes})

        messages = list(consumer.receive(CHANNEL))

        assert messages[0].payload == payload
        assert msg_id in storage.gets

    def test_offloaded_frame_removes_after_yield(self):
        msg_id = "msg-003"
        stored_bytes = json.dumps({"x": 1}).encode()
        frames = [{"id": msg_id, "is_used_storage": True}]
        consumer, _, storage = _consumer(frames, store={msg_id: stored_bytes})

        list(consumer.receive(CHANNEL))

        assert msg_id in storage.removes

    def test_offloaded_but_storage_miss_yields_empty_payload(self):
        msg_id = "msg-004"
        frames = [{"id": msg_id, "is_used_storage": True}]
        consumer, _, storage = _consumer(frames, store={})

        messages = list(consumer.receive(CHANNEL))

        assert messages[0].payload == {}

    def test_is_used_storage_key_not_in_yielded_message(self):
        msg_id = "msg-005"
        stored_bytes = json.dumps({"y": 2}).encode()
        frames = [{"id": msg_id, "is_used_storage": True}]
        consumer, _, storage = _consumer(frames, store={msg_id: stored_bytes})

        messages = list(consumer.receive(CHANNEL))

        assert "is_used_storage" not in messages[0].model_fields_set


async def _collect_async(consumer: Consumer, channel: str) -> list[Message]:
    result = []
    async for message in consumer.areceive(channel):
        result.append(message)
    return result


class TestAsyncReceiveInline:
    @pytest.mark.asyncio
    async def test_inline_frame_yields_message(self):
        payload = {"key": "value"}
        msg_id = "amsg-001"
        frames = [{"id": msg_id, "payload": payload}]
        consumer, _, storage = _consumer(frames)

        messages = await _collect_async(consumer, CHANNEL)

        assert len(messages) == 1
        assert messages[0].id == msg_id
        assert messages[0].payload == payload

    @pytest.mark.asyncio
    async def test_inline_frame_does_not_call_storage_aget(self):
        frames = [{"id": "x", "payload": {"a": 1}}]
        consumer, _, storage = _consumer(frames)
        await _collect_async(consumer, CHANNEL)

        assert len(storage.async_gets) == 0

    @pytest.mark.asyncio
    async def test_inline_frame_does_not_call_storage_aremove(self):
        frames = [{"id": "x", "payload": {"a": 1}}]
        consumer, _, storage = _consumer(frames)
        await _collect_async(consumer, CHANNEL)

        assert len(storage.async_removes) == 0


class TestAsyncReceiveOffloaded:
    @pytest.mark.asyncio
    async def test_offloaded_frame_fetches_from_storage(self):
        payload = {"big": "async-data"}
        msg_id = "amsg-002"
        stored_bytes = json.dumps(payload).encode()
        frames = [{"id": msg_id, "is_used_storage": True}]
        consumer, _, storage = _consumer(frames, store={msg_id: stored_bytes})

        messages = await _collect_async(consumer, CHANNEL)

        assert messages[0].payload == payload
        assert msg_id in storage.async_gets

    @pytest.mark.asyncio
    async def test_offloaded_frame_removes_after_yield(self):
        msg_id = "amsg-003"
        stored_bytes = json.dumps({"x": 1}).encode()
        frames = [{"id": msg_id, "is_used_storage": True}]
        consumer, _, storage = _consumer(frames, store={msg_id: stored_bytes})

        await _collect_async(consumer, CHANNEL)

        assert msg_id in storage.async_removes

    @pytest.mark.asyncio
    async def test_offloaded_but_storage_miss_yields_empty_payload(self):
        msg_id = "amsg-004"
        frames = [{"id": msg_id, "is_used_storage": True}]
        consumer, _, storage = _consumer(frames, store={})

        messages = await _collect_async(consumer, CHANNEL)

        assert messages[0].payload == {}
