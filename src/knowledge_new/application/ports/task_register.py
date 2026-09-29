import abc
import asyncio


class AbstractTaskRegister(abc.ABC):
    @abc.abstractmethod
    def register(self, key: str, task: asyncio.Task):
        """Register the asyncio task by the key."""

    @abc.abstractmethod
    def cancel(self, key: str) -> bool:
        """Cancel the asyncio task by the key."""
