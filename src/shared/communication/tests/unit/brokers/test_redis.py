import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import redis

from communication.brokers.redis_broker import RedisPubSubBroker
from communication.errors import BrokerOperationError


def _make_broker():
    """Return broker + sync_client_mock + async_client_mock with patched from_url."""
    with (
        patch("communication.brokers.redis_broker.SyncRedis.from_url") as sync_from_url,
        patch(
            "communication.brokers.redis_broker.AsyncRedis.from_url"
        ) as async_from_url,
    ):
        sync_mock = MagicMock()
        async_mock = MagicMock()
        sync_from_url.return_value = sync_mock
        async_from_url.return_value = async_mock
        broker = RedisPubSubBroker("redis://localhost:6379/0")

    return broker, sync_mock, async_mock


def _subscribe_frame() -> dict:
    return {"type": "subscribe", "channel": b"ch", "data": 1}


def _message_frame(message: dict) -> dict:
    return {"type": "message", "channel": b"ch", "data": json.dumps(message).encode()}


class TestSyncSend:
    def test_send_publishes_json_encoded_data(self):
        broker, sync_mock, _ = _make_broker()
        data = {"id": "msg-1", "payload": {"x": 1}}
        broker.send("my-channel", data)

        sync_mock.publish.assert_called_once_with("my-channel", json.dumps(data))

    def test_send_redis_error_raises_broker_operation_error(self):
        broker, sync_mock, _ = _make_broker()
        sync_mock.publish.side_effect = redis.RedisError("publish failed")

        with pytest.raises(BrokerOperationError) as exc_info:
            broker.send("ch", {"key": "val"})

        error = exc_info.value
        assert error.operation == "send"
        assert error.channel == "ch"
        assert isinstance(error.__cause__, redis.RedisError)


class TestAsyncSend:
    @pytest.mark.asyncio
    async def test_asend_publishes_json_encoded_data(self):
        broker, _, async_mock = _make_broker()
        async_mock.publish = AsyncMock()
        data = {"id": "msg-2", "payload": {"y": 2}}

        await broker.asend("async-channel", data)

        async_mock.publish.assert_awaited_once_with("async-channel", json.dumps(data))

    @pytest.mark.asyncio
    async def test_asend_redis_error_raises_broker_operation_error(self):
        broker, _, async_mock = _make_broker()
        async_mock.publish = AsyncMock(
            side_effect=redis.RedisError("async publish failed")
        )

        with pytest.raises(BrokerOperationError) as exc_info:
            await broker.asend("async-ch", {"key": "val"})

        error = exc_info.value
        assert error.operation == "asend"
        assert error.channel == "async-ch"
        assert isinstance(error.__cause__, redis.RedisError)


class TestSyncReceive:
    def test_receive_returns_decoded_message_after_subscribe_frame(self):
        broker, sync_mock, _ = _make_broker()
        message = {"id": "m1", "payload": {"a": 1}}
        pubsub = MagicMock()
        pubsub.get_message.side_effect = [_subscribe_frame(), _message_frame(message)]
        sync_mock.pubsub.return_value = pubsub

        result = broker.receive("ch")

        assert result == message
        pubsub.subscribe.assert_called_once_with("ch")
        pubsub.unsubscribe.assert_called_once_with()

    def test_receive_returns_message_when_first_frame_is_message(self):
        broker, sync_mock, _ = _make_broker()
        message = {"id": "m2", "payload": {"b": 2}}
        pubsub = MagicMock()
        pubsub.get_message.side_effect = [_message_frame(message)]
        sync_mock.pubsub.return_value = pubsub

        result = broker.receive("ch")

        assert result == message
        assert pubsub.get_message.call_count == 1

    def test_receive_returns_none_on_immediate_timeout(self):
        broker, sync_mock, _ = _make_broker()
        pubsub = MagicMock()
        pubsub.get_message.side_effect = [None]
        sync_mock.pubsub.return_value = pubsub

        assert broker.receive("ch") is None
        pubsub.unsubscribe.assert_called_once_with()

    def test_receive_returns_none_when_subscribe_frame_then_timeout(self):
        broker, sync_mock, _ = _make_broker()
        pubsub = MagicMock()
        pubsub.get_message.side_effect = [_subscribe_frame(), None]
        sync_mock.pubsub.return_value = pubsub

        assert broker.receive("ch") is None

    def test_receive_passes_timeout_to_get_message(self):
        broker, sync_mock, _ = _make_broker()
        message = {"id": "m", "payload": {}}
        pubsub = MagicMock()
        pubsub.get_message.side_effect = [_message_frame(message)]
        sync_mock.pubsub.return_value = pubsub

        broker.receive("ch", timeout=2.5)

        assert pubsub.get_message.call_args.kwargs["timeout"] == 2.5

    def test_receive_subscribe_redis_error_raises_broker_operation_error(self):
        broker, sync_mock, _ = _make_broker()
        pubsub = MagicMock()
        pubsub.subscribe.side_effect = redis.RedisError("subscribe failed")
        sync_mock.pubsub.return_value = pubsub

        with pytest.raises(BrokerOperationError) as exc_info:
            broker.receive("ch")

        error = exc_info.value
        assert error.operation == "receive"
        assert error.channel == "ch"
        assert isinstance(error.__cause__, redis.RedisError)


class TestAsyncReceive:
    @pytest.mark.asyncio
    async def test_areceive_returns_decoded_message_after_subscribe_frame(self):
        broker, _, async_mock = _make_broker()
        message = {"id": "am1", "payload": {"z": 9}}
        pubsub = MagicMock()
        pubsub.subscribe = AsyncMock()
        pubsub.unsubscribe = AsyncMock()
        pubsub.get_message = AsyncMock(
            side_effect=[_subscribe_frame(), _message_frame(message)]
        )
        async_mock.pubsub.return_value = pubsub

        result = await broker.areceive("ch")

        assert result == message
        pubsub.subscribe.assert_awaited_once_with("ch")
        pubsub.unsubscribe.assert_awaited_once_with()

    @pytest.mark.asyncio
    async def test_areceive_returns_none_on_immediate_timeout(self):
        broker, _, async_mock = _make_broker()
        pubsub = MagicMock()
        pubsub.subscribe = AsyncMock()
        pubsub.unsubscribe = AsyncMock()
        pubsub.get_message = AsyncMock(side_effect=[None])
        async_mock.pubsub.return_value = pubsub

        assert await broker.areceive("ch") is None
        pubsub.unsubscribe.assert_awaited_once_with()

    @pytest.mark.asyncio
    async def test_areceive_subscribe_redis_error_raises_broker_operation_error(self):
        broker, _, async_mock = _make_broker()
        pubsub = MagicMock()
        pubsub.subscribe = AsyncMock(
            side_effect=redis.RedisError("async subscribe failed")
        )
        async_mock.pubsub.return_value = pubsub

        with pytest.raises(BrokerOperationError) as exc_info:
            await broker.areceive("ch")

        error = exc_info.value
        assert error.operation == "areceive"
        assert error.channel == "ch"
        assert isinstance(error.__cause__, redis.RedisError)


class TestSyncStream:
    def test_stream_yields_decoded_messages_skipping_subscribe_frame(self):
        broker, sync_mock, _ = _make_broker()
        messages = [
            {"id": "m1", "payload": {"a": 1}},
            {"id": "m2", "payload": {"b": 2}},
        ]
        frames = [_subscribe_frame(), *[_message_frame(m) for m in messages]]
        pubsub = MagicMock()
        pubsub.listen.return_value = iter(frames)
        sync_mock.pubsub.return_value = pubsub

        result = list(broker.stream("ch"))

        assert result == messages
        pubsub.subscribe.assert_called_once_with("ch")

    def test_stream_skips_non_message_frames(self):
        broker, sync_mock, _ = _make_broker()
        data = {"id": "only", "payload": {}}
        frames = [
            {"type": "subscribe", "channel": b"ch", "data": 1},
            {"type": "psubscribe", "channel": b"ch", "data": 1},
            _message_frame(data),
        ]
        pubsub = MagicMock()
        pubsub.listen.return_value = iter(frames)
        sync_mock.pubsub.return_value = pubsub

        assert list(broker.stream("ch")) == [data]

    def test_stream_subscribe_redis_error_raises_broker_operation_error(self):
        broker, sync_mock, _ = _make_broker()
        pubsub = MagicMock()
        pubsub.subscribe.side_effect = redis.RedisError("subscribe failed")
        sync_mock.pubsub.return_value = pubsub

        with pytest.raises(BrokerOperationError) as exc_info:
            list(broker.stream("ch"))

        error = exc_info.value
        assert error.operation == "stream"
        assert error.channel == "ch"
        assert isinstance(error.__cause__, redis.RedisError)


class TestAsyncStream:
    @pytest.mark.asyncio
    async def test_astream_yields_decoded_messages_skipping_subscribe_frame(self):
        broker, _, async_mock = _make_broker()
        messages = [
            {"id": "am1", "payload": {"z": 9}},
            {"id": "am2", "payload": {"y": 8}},
        ]

        async def fake_listen():
            yield _subscribe_frame()
            for message in messages:
                yield _message_frame(message)

        pubsub = MagicMock()
        pubsub.subscribe = AsyncMock()
        pubsub.unsubscribe = AsyncMock()
        pubsub.listen = fake_listen
        async_mock.pubsub.return_value = pubsub

        result = [item async for item in broker.astream("ch")]

        assert result == messages
        pubsub.subscribe.assert_awaited_once_with("ch")

    @pytest.mark.asyncio
    async def test_astream_subscribe_redis_error_raises_broker_operation_error(self):
        broker, _, async_mock = _make_broker()
        pubsub = MagicMock()
        pubsub.subscribe = AsyncMock(
            side_effect=redis.RedisError("async subscribe failed")
        )
        async_mock.pubsub.return_value = pubsub

        with pytest.raises(BrokerOperationError) as exc_info:
            async for _ in broker.astream("ch"):
                pass

        error = exc_info.value
        assert error.operation == "astream"
        assert error.channel == "ch"
        assert isinstance(error.__cause__, redis.RedisError)
