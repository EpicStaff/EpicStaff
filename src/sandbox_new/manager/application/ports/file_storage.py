import abc
from typing import BinaryIO

__all__ = ["AbstractFileStorage"]


class AbstractFileStorage(abc.ABC):
    """Object store the manager keeps uploaded and built artifacts in.

    Keys are built by the domain, so this port only moves bytes: it knows nothing
    about libraries, wheels or the layout they are stored under.
    """

    @abc.abstractmethod
    async def put(self, key: str, file: BinaryIO):
        """Store `file` under `key`, replacing whatever was there.

        Args:
            key: Where to store it.
            file: Readable binary file object, consumed from its current position.
                It is sent in parts, so its size is not bounded by memory.
        """

    @abc.abstractmethod
    async def get(self, key: str) -> bytes:
        """Return the whole object stored under `key`.

        Note:
            Reads it into memory in one piece; there is no streaming read yet.

        Raises:
            FileNotFoundError: Nothing is stored under this key.
        """

    @abc.abstractmethod
    async def delete(self, key: str):
        """Remove the object at `key`. A key that is not there is not an error."""
