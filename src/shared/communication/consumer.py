import json
from typing import Iterable, AsyncIterable

from communication.message import Message
from communication.brokers import AbstractBroker
from communication.storages import AbstractStorage


class Consumer:
    """Receives messages from a broker, restoring payloads that were offloaded
    to storage.

    Args:
        broker: Broker to read from.
        storage: Store to fetch offloaded payloads from.
    """

    def __init__(self, broker: AbstractBroker, storage: AbstractStorage):
        self.broker = broker
        self.storage = storage

    def receive(self, channel: str) -> Iterable[Message]:
        """Receive messages from a channel synchronously.

        Args:
            channel: Channel to receive from.
        """
        for data in self.broker.receive(channel):
            msg_id = data["id"]
            is_used_storage = data.pop("is_used_storage", False)
            if is_used_storage:
                payload = self.storage.get(msg_id)
                data["payload"] = json.loads(payload) if payload else {}

            yield Message(**data)

            if is_used_storage:
                self.storage.remove(msg_id)

    async def areceive(self, channel: str) -> AsyncIterable[Message]:
        """Receive messages from a channel asynchronously.

        Args:
            channel: Channel to receive from.
        """
        async for data in self.broker.areceive(channel):
            msg_id = data["id"]
            is_used_storage = data.pop("is_used_storage", False)
            if is_used_storage:
                payload = await self.storage.aget(msg_id)
                data["payload"] = json.loads(payload) if payload else {}

            yield Message(**data)

            if is_used_storage:
                await self.storage.aremove(msg_id)
