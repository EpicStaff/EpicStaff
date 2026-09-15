from abc import ABC, abstractmethod
from typing import Any, AsyncIterator, Iterator


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
    def receive(self, channel: str, timeout: float = 5.0) -> dict[str, Any] | None:
        """Receive the next message from a channel synchronously.

        Implementations must block for up to `timeout` seconds and return `None`
        if no message arrives in that window.

        Args:
            channel: Channel to receive from.
            timeout: Seconds to wait for a message. Defaults to `5.0`.

        Returns:
            The next message as the same dict passed to `send`, or `None` if the
            timeout elapses with no message.
        """

    @abstractmethod
    async def areceive(
        self,
        channel: str,
        timeout: float = 5.0,
    ) -> dict[str, Any] | None:
        """Receive the next message from a channel asynchronously.

        Implementations must wait for up to `timeout` seconds and return `None`
        if no message arrives in that window.

        Args:
            channel: Channel to receive from.
            timeout: Seconds to wait for a message. Defaults to `5.0`.

        Returns:
            The next message as the same dict passed to `send`, or `None` if the
            timeout elapses with no message.
        """

    @abstractmethod
    def stream(self, channel: str) -> Iterator[dict[str, Any]]:
        """Yield messages from a channel synchronously as they arrive.

        Implementations must return an unbounded iterator that blocks until the
        next message and yields it as the same dict passed to `send`. The caller
        is responsible for calling `close` when done.

        Args:
            channel: Channel to stream from.

        Yields:
            Each message as the same dict passed to `send`.
        """

    @abstractmethod
    async def astream(self, channel: str) -> AsyncIterator[dict[str, Any]]:
        """Yield messages from a channel asynchronously as they arrive.

        Implementations must return an unbounded async iterator that blocks until
        the next message and yields it as the same dict passed to `send`. The
        caller is responsible for calling `aclose` when done.

        Args:
            channel: Channel to stream from.

        Yields:
            Each message as the same dict passed to `send`.
        """
