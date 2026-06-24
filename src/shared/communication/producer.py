import json
from os import getenv

from communication.message import Message
from communication.brokers import AbstractBroker
from communication.storages import AbstractStorage


DEFAULT_PAYLOAD_SIZE_THRESHOLD = int(
    getenv("DEFAULT_PAYLOAD_SIZE_THRESHOLD", 1024**2)
)  # 1MB


class Producer:
    """Sends messages over a broker, offloading payloads larger than the size
    threshold to storage.

    Args:
        broker: Broker to publish through.
        storage: Store for offloaded payloads.
        payload_size_threshold: Byte size above which a payload is offloaded.
            Defaults to 1 MB.
    """

    def __init__(
        self,
        broker: AbstractBroker,
        storage: AbstractStorage,
        payload_size_threshold: int = DEFAULT_PAYLOAD_SIZE_THRESHOLD,
    ):
        self._broker = broker
        self._storage = storage
        self._payload_size_threshold = payload_size_threshold

    def send(self, channel: str, message: Message):
        """Send a message to a channel synchronously.

        Args:
            channel: Channel to send to.
            message: Message to send.
        """
        raw_payload = json.dumps(message.payload).encode()
        if len(raw_payload) > self._payload_size_threshold:
            self._storage.put(message.id, raw_payload)
            data = {"id": message.id, "is_used_storage": True}
        else:
            data = message.model_dump()

        self._broker.send(channel, data)

    async def asend(self, channel: str, message: Message):
        """Send a message to a channel asynchronously.

        Args:
            channel: Channel to send to.
            message: Message to send.
        """
        raw_payload = json.dumps(message.payload).encode()
        if len(raw_payload) > self._payload_size_threshold:
            await self._storage.aput(message.id, raw_payload)
            data = {"id": message.id, "is_used_storage": True}
        else:
            data = message.model_dump()

        await self._broker.asend(channel, data)
