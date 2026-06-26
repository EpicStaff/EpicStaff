import asyncio
import threading
import time

import pytest

pytestmark = pytest.mark.integration

from communication.brokers.redis_ import RedisPubSubBroker

CHANNEL = "integ-broker-channel"
TIMEOUT = 10  # seconds to wait for a message before failing


class TestSyncRoundtrip:
    def test_send_receive_roundtrip(self, redis_url):
        """Publish a message from main thread; subscriber thread collects it."""
        broker = RedisPubSubBroker(redis_url)
        data = {"id": "broker-integ-1", "payload": {"hello": "world"}}

        received: list[dict] = []
        ready = threading.Event()
        done = threading.Event()

        def subscriber():
            gen = broker.receive(CHANNEL)
            ready.set()
            try:
                msg = next(iter(gen))
                received.append(msg)
            finally:
                done.set()

        thread = threading.Thread(target=subscriber, daemon=True)
        thread.start()

        # Wait until subscriber has subscribed before publishing.
        ready.wait(timeout=5)
        time.sleep(0.1)  # brief grace period for the pubsub subscription to activate

        broker.send(CHANNEL, data)
        done.wait(timeout=TIMEOUT)

        assert received == [data]

    def test_send_receive_multiple_messages(self, redis_url):
        broker = RedisPubSubBroker(redis_url)
        messages = [{"id": f"broker-integ-m{i}", "payload": {"i": i}} for i in range(3)]

        received: list[dict] = []
        ready = threading.Event()
        done = threading.Event()

        def subscriber():
            gen = broker.receive(CHANNEL + "-multi")
            ready.set()
            for _ in messages:
                received.append(next(iter(gen)))
            done.set()

        thread = threading.Thread(target=subscriber, daemon=True)
        thread.start()

        ready.wait(timeout=5)
        time.sleep(0.1)

        for msg in messages:
            broker.send(CHANNEL + "-multi", msg)

        done.wait(timeout=TIMEOUT)
        assert received == messages


class TestAsyncRoundtrip:
    @pytest.mark.asyncio
    async def test_asend_areceive_roundtrip(self, redis_url):
        broker = RedisPubSubBroker(redis_url)
        data = {"id": "abroker-integ-1", "payload": {"async": True}}

        received: list[dict] = []

        async def subscriber_task():
            async for msg in broker.areceive(CHANNEL + "-async"):
                received.append(msg)
                return  # stop after first message

        task = asyncio.create_task(subscriber_task())

        # Give the subscriber a moment to subscribe.
        await asyncio.sleep(0.2)
        await broker.asend(CHANNEL + "-async", data)

        try:
            await asyncio.wait_for(task, timeout=TIMEOUT)
        except asyncio.TimeoutError:
            task.cancel()
            pytest.fail("Subscriber did not receive the message within timeout")

        assert received == [data]

    @pytest.mark.asyncio
    async def test_asend_areceive_multiple_messages(self, redis_url):
        broker = RedisPubSubBroker(redis_url)
        messages = [
            {"id": f"abroker-integ-m{i}", "payload": {"i": i}} for i in range(3)
        ]

        received: list[dict] = []

        async def subscriber_task():
            async for msg in broker.areceive(CHANNEL + "-async-multi"):
                received.append(msg)
                if len(received) >= len(messages):
                    return

        task = asyncio.create_task(subscriber_task())
        await asyncio.sleep(0.2)

        for msg in messages:
            await broker.asend(CHANNEL + "-async-multi", msg)

        try:
            await asyncio.wait_for(task, timeout=TIMEOUT)
        except asyncio.TimeoutError:
            task.cancel()
            pytest.fail("Subscriber did not receive all messages within timeout")

        assert received == messages
