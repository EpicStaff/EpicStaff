import asyncio
import threading
import time

import pytest

pytestmark = pytest.mark.integration

from communication.brokers.redis_broker import RedisPubSubBroker

CHANNEL = "integ-broker-channel"
TIMEOUT = 10  # seconds to wait for a message before failing
SUBSCRIBE_GRACE = 0.5  # let the subscription activate before publishing


class TestSyncReceive:
    def test_receive_returns_published_message(self, redis_url):
        broker = RedisPubSubBroker(redis_url)
        channel = CHANNEL + "-recv"
        data = {"id": "broker-integ-1", "payload": {"hello": "world"}}

        result: list = []

        def subscriber():
            result.append(broker.receive(channel, timeout=TIMEOUT))

        thread = threading.Thread(target=subscriber, daemon=True)
        thread.start()
        time.sleep(SUBSCRIBE_GRACE)
        broker.send(channel, data)
        thread.join(timeout=TIMEOUT + 2)

        assert result == [data]

    def test_receive_returns_none_on_timeout(self, redis_url):
        broker = RedisPubSubBroker(redis_url)
        assert broker.receive(CHANNEL + "-empty", timeout=1.0) is None


class TestAsyncReceive:
    @pytest.mark.asyncio
    async def test_areceive_returns_published_message(self, redis_url):
        broker = RedisPubSubBroker(redis_url)
        channel = CHANNEL + "-arecv"
        data = {"id": "abroker-integ-1", "payload": {"async": True}}

        task = asyncio.create_task(broker.areceive(channel, timeout=TIMEOUT))
        await asyncio.sleep(SUBSCRIBE_GRACE)
        await broker.asend(channel, data)
        result = await asyncio.wait_for(task, timeout=TIMEOUT + 2)

        assert result == data

    @pytest.mark.asyncio
    async def test_areceive_returns_none_on_timeout(self, redis_url):
        broker = RedisPubSubBroker(redis_url)
        assert await broker.areceive(CHANNEL + "-aempty", timeout=1.0) is None


class TestSyncStream:
    def test_stream_yields_published_messages_in_order(self, redis_url):
        broker = RedisPubSubBroker(redis_url)
        channel = CHANNEL + "-stream"
        messages = [{"id": f"broker-integ-m{i}", "payload": {"i": i}} for i in range(3)]

        received: list = []

        def subscriber():
            for msg in broker.stream(channel):
                received.append(msg)
                if len(received) >= len(messages):
                    break

        thread = threading.Thread(target=subscriber, daemon=True)
        thread.start()
        time.sleep(SUBSCRIBE_GRACE)
        for msg in messages:
            broker.send(channel, msg)
        thread.join(timeout=TIMEOUT)

        assert received == messages


class TestAsyncStream:
    @pytest.mark.asyncio
    async def test_astream_yields_published_messages_in_order(self, redis_url):
        broker = RedisPubSubBroker(redis_url)
        channel = CHANNEL + "-astream"
        messages = [
            {"id": f"abroker-integ-m{i}", "payload": {"i": i}} for i in range(3)
        ]

        received: list = []

        async def subscriber():
            async for msg in broker.astream(channel):
                received.append(msg)
                if len(received) >= len(messages):
                    return

        task = asyncio.create_task(subscriber())
        await asyncio.sleep(SUBSCRIBE_GRACE)
        for msg in messages:
            await broker.asend(channel, msg)
        await asyncio.wait_for(task, timeout=TIMEOUT)

        assert received == messages
