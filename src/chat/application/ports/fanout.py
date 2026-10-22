import abc
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager


class AbstractFanout(abc.ABC):
    """Wake-up bus for the streams. The event table is the truth; this only says "look again"."""

    @abc.abstractmethod
    async def publish(self, channel: str, event: dict) -> None: ...

    @abc.abstractmethod
    def listen(
        self, channel: str, idle_seconds: float
    ) -> AbstractAsyncContextManager[AsyncIterator[dict | None]]:
        """Subscribe on enter; the iterator yields each event dict and None after `idle_seconds` of silence."""
