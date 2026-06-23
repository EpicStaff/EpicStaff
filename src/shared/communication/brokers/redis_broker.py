import json
from typing import Any, Iterator, AsyncIterator

from redis import Redis as SyncRedis, RedisError
from redis.asyncio import Redis as AsyncRedis

from ..errors import BrokerOperationError
from ..error_handler import handle_error
from .abstract import AbstractBroker


class RedisPubSubBroker(AbstractBroker):
    """Redis Pub/Sub implementation of `AbstractBroker`.

    Messages are delivered only to subscribers connected at publish time; Redis
    Pub/Sub keeps no backlog, so anything published to a channel while nothing is
    subscribed is dropped. Every `receive` and `stream` call opens its own
    subscription and tears it down when it finishes. Any failing Redis call is
    re-raised as `BrokerOperationError`.

    Args:
        url: Redis connection URL (e.g. `redis://host:6379/0`).
    """

    def __init__(self, url: str):
        self._sync_client = SyncRedis.from_url(url, socket_timeout=None)
        self._async_client = AsyncRedis.from_url(url, socket_timeout=None)

    def send(self, channel: str, data: dict[str, Any]):
        """Publish `data` to `channel`.

        Reaches only clients subscribed at publish time; with no subscriber the
        message is dropped.

        Args:
            channel: Channel to publish to.
            data: JSON-serializable dict to deliver.
        """
        with handle_error(RedisError, BrokerOperationError, "send", channel):
            raw_data = json.dumps(data)
            self._sync_client.publish(channel, raw_data)

    async def asend(self, channel: str, data: dict[str, Any]):
        """Publish `data` to `channel` asynchronously.

        Reaches only clients subscribed at publish time; with no subscriber the
        message is dropped.

        Args:
            channel: Channel to publish to.
            data: JSON-serializable dict to deliver.
        """
        with handle_error(RedisError, BrokerOperationError, "asend", channel):
            raw_data = json.dumps(data)
            await self._async_client.publish(channel, raw_data)

    def receive(self, channel: str, timeout: float = 5.0) -> dict[str, Any] | None:
        """Subscribe to `channel`, wait for one message, then unsubscribe.

        The first frame after subscribing is Redis's subscribe confirmation, which is
        skipped; the effective wait for an actual message can therefore reach roughly
        twice `timeout`.

        Args:
            channel: Channel to receive from.
            timeout: Seconds to wait for a message. Defaults to `5.0`.

        Returns:
            The published message as the dict passed to `send`, or `None` if no
            message arrives.
        """
        with handle_error(RedisError, BrokerOperationError, "receive", channel):
            pubsub = self._sync_client.pubsub()
            pubsub.subscribe(channel)
            try:
                msg = pubsub.get_message(timeout=timeout)
                if msg and msg['type'] != 'message':
                    msg = pubsub.get_message(timeout=timeout)

                if msg is None:
                    return None
                return json.loads(msg['data'])
            finally:
                pubsub.unsubscribe()

    async def areceive(self, channel: str, timeout: float = 5.0) -> dict[str, Any] | None:
        """Subscribe to `channel`, wait for one message, then unsubscribe, asynchronously.

        The first frame after subscribing is Redis's subscribe confirmation, which is
        skipped; the effective wait for an actual message can therefore reach roughly
        twice `timeout`.

        Args:
            channel: Channel to receive from.
            timeout: Seconds to wait for a message. Defaults to `5.0`.

        Returns:
            The published message as the dict passed to `send`, or `None` if no
            message arrives.
        """
        with handle_error(RedisError, BrokerOperationError, "areceive", channel):
            pubsub = self._async_client.pubsub()
            await pubsub.subscribe(channel)
            try:
                msg = await pubsub.get_message(timeout=timeout)
                if msg and msg['type'] != 'message':
                    msg = await pubsub.get_message(timeout=timeout)
                if msg is None:
                    return None
                return json.loads(msg['data'])
            finally:
                await pubsub.unsubscribe()

    def stream(self, channel: str) -> Iterator[dict[str, Any]]:
        """Subscribe to `channel` and yield each published message until iteration stops.

        The subscription is held for the lifetime of the iterator and released when
        the generator is closed; stop iterating to free it.

        Args:
            channel: Channel to stream from.

        Yields:
            Each published message as the dict passed to `send`.
        """
        with handle_error(RedisError, BrokerOperationError, "stream", channel):
            pubsub = self._sync_client.pubsub()
            pubsub.subscribe(channel)
            try:
                for msg in pubsub.listen():
                    if msg['type'] != 'message':
                        continue
                    yield json.loads(msg['data'])
            finally:
                pubsub.unsubscribe()

    async def astream(self, channel: str) -> AsyncIterator[dict[str, Any]]:
        """Subscribe to `channel` and yield each published message asynchronously until iteration stops.

        The subscription is held for the lifetime of the iterator and released when
        the generator is closed; stop iterating to free it.

        Args:
            channel: Channel to stream from.

        Yields:
            Each published message as the dict passed to `send`.
        """
        with handle_error(RedisError, BrokerOperationError, "astream", channel):
            pubsub = self._async_client.pubsub()
            await pubsub.subscribe(channel)
            try:
                async for msg in pubsub.listen():
                    if msg['type'] != 'message':
                        continue
                    yield json.loads(msg['data'])
            finally:
                await pubsub.unsubscribe()
