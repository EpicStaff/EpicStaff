from abc import ABC, abstractmethod


class AbstractStorage(ABC):
    """Abstraction of a key/value store for offloaded message payloads.

    Implement it to back offloading with a new store (e.g. MinIO, S3); keep
    storage-specific configuration in the implementation's constructor.
    """

    @abstractmethod
    def put(self, key: str, payload: bytes):
        """Store a payload under a key syncronously.

        Persist `payload` under `key`. A TTL is allowed — callers must not
        assume the data lives forever.

        Args:
            key: Identifier to store under.
            payload: Raw bytes to store.
        """

    @abstractmethod
    async def aput(self, key: str, payload: bytes):
        """Store a payload under a key asyncronously.

        Persist `payload` under `key`. A TTL is allowed — callers must not
        assume the data lives forever.

        Args:
            key: Identifier to store under.
            payload: Raw bytes to store.
        """

    @abstractmethod
    def get(self, key: str) -> bytes | None:
        """Fetch the payload stored under a key synchronously.

        Returns the stored bytes, or None if the key is absent or expired; never
        raises on a miss.

        Args:
            key: Identifier to look up.
        """

    @abstractmethod
    async def aget(self, key: str) -> bytes | None:
        """Fetch the payload stored under a key asynchronously.

        Returns the stored bytes, or None if the key is absent or expired; never
        raises on a miss.

        Args:
            key: Identifier to look up.
        """

    @abstractmethod
    def remove(self, key: str):
        """Delete the payload stored under a key synchronously.

        A  missing key will be a no-op, not an error.

        Args:
            key: Identifier to delete.
        """

    @abstractmethod
    async def aremove(self, key: str):
        """Delete the payload stored under a key asynchronously.

        A  missing key will be a no-op, not an error.

        Args:
            key: Identifier to delete.
        """
