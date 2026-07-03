from abc import ABC, abstractmethod
from typing import Iterable, Any, AsyncIterable


class AbstractBroker(ABC):
    """Abstraction of a message transport — sending to and receiving from named
    channels.

    Implement it to support a new broker (e.g. RabbitMQ, Kafka); keep
    broker-specific configuration in the implementation's constructor.
    """

    @abstractmethod
    def send(self, channel: str, data: dict[str, Any]):
        """Send one message to a channel synchronously.

        Args:
            channel: Channel to send to.
            data: JSON-serializable dict to deliver.
        """

    @abstractmethod
    async def asend(self, channel: str, data: dict[str, Any]):
        """Send one message to a channel asynchronously.

        Args:
            channel: Channel to send to.
            data: JSON-serializable dict to deliver.
        """

    @abstractmethod
    def receive(self, channel: str) -> Iterable[dict[str, Any]]:
        """Receive messages from a channel synchronously.

        Return an unbounded iterator that blocks until the next message and
        yields it as the same dict passed to send.

        Args:
            channel: Channel to receive from.
        """

    @abstractmethod
    async def areceive(self, channel: str) -> AsyncIterable[dict[str, Any]]:
        """Receive messages from a channel asynchronously.

        Return an unbounded async iterator that blocks until the next message and
        yields it as the same dict passed to send.

        Args:
            channel: Channel to receive from.
        """
