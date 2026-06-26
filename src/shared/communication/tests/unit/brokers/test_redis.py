import json
from unittest.mock import MagicMock, patch

import pytest
import redis

from communication.brokers.redis_ import RedisPubSubBroker
from communication.errors import BrokerOperationError


def _make_broker() -> tuple[RedisPubSubBroker, MagicMock, MagicMock]:
    """Return broker + sync_client_mock + async_client_mock.

    We patch both redis.Redis.from_url and redis.asyncio.Redis.from_url so
    no real network connection is attempted.
    """
    with (
        patch("communication.brokers.redis_.SyncRedis.from_url") as sync_from_url,
        patch("communication.brokers.redis_.AsyncRedis.from_url") as async_from_url,
    ):
        sync_mock = MagicMock()
        async_mock = MagicMock()
        sync_from_url.return_value = sync_mock
        async_from_url.return_value = async_mock
        broker = RedisPubSubBroker("redis://localhost:6379/0")

    return broker, sync_mock, async_mock


def _build_listen_frames(
    messages: list[dict], include_subscribe_frame=True
) -> list[dict]:
    """Build a fake pubsub.listen() frame list."""
    frames = []
    if include_subscribe_frame:
        frames.append({"type": "subscribe", "channel": b"ch", "data": 1})
    for message in messages:
        frames.append(
            {"type": "message", "channel": b"ch", "data": json.dumps(message).encode()}
        )
    return frames


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

        async def fake_publish(channel, data):
            pass

        async_mock.publish = fake_publish
        data = {"id": "msg-2", "payload": {"y": 2}}

        # No exception means success; verify by replacing publish with a recorder
        published_calls = []

        async def recording_publish(channel, data):
            published_calls.append((channel, data))

        async_mock.publish = recording_publish
        await broker.asend("async-channel", data)

        assert len(published_calls) == 1
        assert published_calls[0] == ("async-channel", json.dumps(data))

    @pytest.mark.asyncio
    async def test_asend_redis_error_raises_broker_operation_error(self):
        broker, _, async_mock = _make_broker()

        async def raise_redis_error(*args, **kwargs):
            raise redis.RedisError("async publish failed")

        async_mock.publish = raise_redis_error

        with pytest.raises(BrokerOperationError) as exc_info:
            await broker.asend("async-ch", {"key": "val"})

        error = exc_info.value
        assert error.operation == "asend"
        assert error.channel == "async-ch"
        assert isinstance(error.__cause__, redis.RedisError)


class TestSyncReceive:
    def test_receive_yields_decoded_message_dicts(self):
        broker, sync_mock, _ = _make_broker()
        messages = [
            {"id": "m1", "payload": {"a": 1}},
            {"id": "m2", "payload": {"b": 2}},
        ]
        frames = _build_listen_frames(messages)

        mock_pubsub = MagicMock()
        mock_pubsub.listen.return_value = iter(frames)
        sync_mock.pubsub.return_value = mock_pubsub

        result = list(broker.receive("ch"))

        assert result == messages

    def test_receive_skips_non_message_frames(self):
        broker, sync_mock, _ = _make_broker()
        data = {"id": "m-only", "payload": {}}
        frames = [
            {"type": "subscribe", "channel": b"ch", "data": 1},
            {"type": "psubscribe", "channel": b"ch", "data": 1},
            {"type": "message", "channel": b"ch", "data": json.dumps(data).encode()},
        ]

        mock_pubsub = MagicMock()
        mock_pubsub.listen.return_value = iter(frames)
        sync_mock.pubsub.return_value = mock_pubsub

        result = list(broker.receive("ch"))

        assert result == [data]

    def test_receive_subscribe_redis_error_raises_broker_operation_error(self):
        broker, sync_mock, _ = _make_broker()

        mock_pubsub = MagicMock()
        mock_pubsub.subscribe.side_effect = redis.RedisError("subscribe failed")
        sync_mock.pubsub.return_value = mock_pubsub

        with pytest.raises(BrokerOperationError) as exc_info:
            list(broker.receive("ch"))

        error = exc_info.value
        assert error.operation == "receive"
        assert error.channel == "ch"
        assert isinstance(error.__cause__, redis.RedisError)


class TestAsyncReceive:
    @pytest.mark.asyncio
    async def test_areceive_yields_decoded_message_dicts(self):
        broker, _, async_mock = _make_broker()
        messages = [{"id": "am1", "payload": {"z": 9}}]

        async def fake_listen():
            yield {"type": "subscribe", "data": 1}
            for msg in messages:
                yield {
                    "type": "message",
                    "channel": b"ch",
                    "data": json.dumps(msg).encode(),
                }

        mock_pubsub = MagicMock()
        mock_pubsub.subscribe = MagicMock(return_value=None)

        async def async_subscribe(*args, **kwargs):
            pass

        mock_pubsub.subscribe = async_subscribe
        mock_pubsub.listen = fake_listen
        async_mock.pubsub.return_value = mock_pubsub

        result = []
        async for item in broker.areceive("ch"):
            result.append(item)

        assert result == messages

    @pytest.mark.asyncio
    async def test_areceive_skips_non_message_frames(self):
        broker, _, async_mock = _make_broker()
        data = {"id": "am-only", "payload": {}}

        async def fake_listen():
            yield {"type": "psubscribe", "data": 1}
            yield {
                "type": "message",
                "channel": b"ch",
                "data": json.dumps(data).encode(),
            }

        mock_pubsub = MagicMock()

        async def async_subscribe(*args, **kwargs):
            pass

        mock_pubsub.subscribe = async_subscribe
        mock_pubsub.listen = fake_listen
        async_mock.pubsub.return_value = mock_pubsub

        result = []
        async for item in broker.areceive("ch"):
            result.append(item)

        assert result == [data]

    @pytest.mark.asyncio
    async def test_areceive_subscribe_redis_error_raises_broker_operation_error(self):
        broker, _, async_mock = _make_broker()

        mock_pubsub = MagicMock()

        async def raising_subscribe(*args, **kwargs):
            raise redis.RedisError("async subscribe failed")

        mock_pubsub.subscribe = raising_subscribe
        async_mock.pubsub.return_value = mock_pubsub

        with pytest.raises(BrokerOperationError) as exc_info:
            async for _ in broker.areceive("ch"):
                pass

        error = exc_info.value
        assert error.operation == "areceive"
        assert error.channel == "ch"
        assert isinstance(error.__cause__, redis.RedisError)
