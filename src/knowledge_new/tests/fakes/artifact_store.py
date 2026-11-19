from collections.abc import AsyncIterator
from typing import BinaryIO

from application.ports.artifact_store import AbstractArtifactStore, StoredObject


class InMemoryArtifactStore(AbstractArtifactStore):
    """Holds objects as bytes and streams them in small chunks, like S3 does in larger ones."""

    def __init__(self, objects: dict[str, bytes] | None = None, chunk_size: int = 7) -> None:
        self.objects = {} if objects is None else objects
        self.chunk_size = chunk_size

    async def list_objects(self, prefix: str) -> list[StoredObject]:
        return [
            StoredObject(key=key, size=len(data))
            for key, data in self.objects.items()
            if key.startswith(prefix)
        ]

    async def iter_object(self, key: str) -> AsyncIterator[bytes]:
        data = self.objects[key]
        for start in range(0, len(data), self.chunk_size):
            yield data[start : start + self.chunk_size]

    async def put(self, key: str, source: BinaryIO, size: int) -> None:
        self.objects[key] = source.read(size)

    async def clear(self, prefix: str) -> None:
        for key in [key for key in self.objects if key.startswith(prefix)]:
            del self.objects[key]
