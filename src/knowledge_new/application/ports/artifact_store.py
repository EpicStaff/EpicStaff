from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import BinaryIO


@dataclass(frozen=True)
class StoredObject:
    """An object in the artifact store: its full key and its size in bytes, as listed."""

    key: str
    size: int


class AbstractArtifactStore(ABC):
    """Object storage holding GraphRAG artifacts, addressed by full keys in the knowledge bucket.

    Export and restore of a graph RAG's index go through this port, so their
    orchestrators can be tested against an in-memory fake. Objects are read as a
    stream and never loaded whole, because a LanceDB data file can be large.
    """

    @abstractmethod
    async def list_objects(self, prefix: str) -> list[StoredObject]:
        """Return every object stored under `prefix`, at any depth, with its size.

        The size comes from the listing itself: export writes each tar header from
        it before reading the object.

        Args:
            prefix: Key prefix such as `graphrag/rag_7/a/`. End it with `/`, or
                `graphrag/rag_7` also matches the objects of `graphrag/rag_70`.

        Returns:
            The objects under `prefix`, each with its full key and size in bytes.
            Empty when nothing is stored there; that is not an error.
        """

    @abstractmethod
    def iter_object(self, key: str) -> AsyncIterator[bytes]:
        """Yield the bytes of the object at `key` in chunks.

        Args:
            key: Full key of the object, as returned by `list_objects`.

        Raises:
            Exception: If the object no longer exists, for example because an
                indexing run swapped slots and cleared the old one after `list_objects`.
                The caller treats this as a failed export.
        """

    @abstractmethod
    async def put(self, key: str, source: BinaryIO, size: int) -> None:
        """Store `size` bytes read from `source` at `key`, replacing any object there.

        Args:
            key: Full key to write, such as `graphrag/rag_7/a/output/entities.parquet`.
            source: Readable binary stream positioned at the start of the data.
            size: Exact number of bytes to read from `source`. S3 needs the
                length before the upload starts.
        """

    @abstractmethod
    async def clear(self, prefix: str) -> None:
        """Delete every object stored under `prefix`, at any depth.

        Does nothing when nothing is stored there, so it is safe to call before a
        restore and again after a failed one.

        Args:
            prefix: Key prefix such as `graphrag/rag_7/`. End it with `/` for the
                same reason as in `list_objects`.
        """
