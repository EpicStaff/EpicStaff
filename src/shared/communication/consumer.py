import json
from typing import Iterator, AsyncIterator, Any

from .message import Message
from .brokers import AbstractBroker
from .storages import AbstractStorage


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

    def receive(self, channel: str, timeout: float = 5.0) -> Message | None:
        """Receive the next message from `channel`, or `None` if none arrives.

        Restores an offloaded payload from storage and deletes it before returning.

        Args:
            channel: Channel to receive from.
            timeout: Seconds to wait for a message. Defaults to `5.0`.

        Returns:
            The next message, or `None` if the timeout elapses with no message.
        """
        data = self.broker.receive(channel, timeout=timeout)
        if data is None:
            return None
        data = self._update_data_by_payload_from_storage_if_exists(data)
        return Message(**data)

    async def areceive(self, channel: str, timeout: float = 5.0) -> Message | None:
        """Receive the next message from `channel` asynchronously, or `None` if none arrives.

        Restores an offloaded payload from storage and deletes it before returning.

        Args:
            channel: Channel to receive from.
            timeout: Seconds to wait for a message. Defaults to `5.0`.

        Returns:
            The next message, or `None` if the timeout elapses with no message.
        """
        data = await self.broker.areceive(channel, timeout=timeout)
        if data is None:
            return None
        data = await self._aupdate_data_by_payload_from_storage_if_exists(data)
        return Message(**data)

    def stream(self, channel: str) -> Iterator[Message]:
        """Yield messages from `channel` as they arrive.

        Restores each offloaded payload from storage and deletes it before the
        message is yielded.

        Args:
            channel: Channel to stream from.

        Yields:
            Each message as it arrives.
        """
        for data in self.broker.stream(channel):
            data = self._update_data_by_payload_from_storage_if_exists(data)
            yield Message(**data)


    async def astream(self, channel: str) -> AsyncIterator[Message]:
        """Yield messages from `channel` asynchronously as they arrive.

        Restores each offloaded payload from storage and deletes it before the
        message is yielded.

        Args:
            channel: Channel to stream from.

        Yields:
            Each message as it arrives.
        """
        async for data in self.broker.astream(channel):
            data = await self._aupdate_data_by_payload_from_storage_if_exists(data)
            yield Message(**data)

    def _update_data_by_payload_from_storage_if_exists(self, data: dict[str, Any]) -> dict[str, Any]:
        msg_id = data['id']
        if data.pop("is_used_storage", False):
            payload = self.storage.get(msg_id)
            data["payload"] = json.loads(payload) if payload else {}
            self.storage.remove(msg_id)
        return data

    async def _aupdate_data_by_payload_from_storage_if_exists(self, data: dict[str, Any]) -> dict[str, Any]:
        msg_id = data['id']
        if data.pop("is_used_storage", False):
            payload = await self.storage.aget(msg_id)
            data["payload"] = json.loads(payload) if payload else {}
            await self.storage.aremove(msg_id)
        return data
