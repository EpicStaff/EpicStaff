import abc
import asyncio


class AbstractTaskRegister(abc.ABC):
    def register(self, key: str, task: asyncio.Task):
        """Register the asyncio task by the key."""

    def cancel(self, key: str) -> bool:
        """Cancel the asyncio task by the key."""
