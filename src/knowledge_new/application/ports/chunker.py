import abc

from domain.errors import ChunkingError
from domain.models import ChunkingConfig, PreviewChunk


class AbstractChunker(abc.ABC):
    """Abstract base for splitting text into preview chunks."""

    def __init__(self, config: ChunkingConfig):
        self.config = config

    async def chunk(self, text: str) -> list[PreviewChunk]:
        """Split `text` into preview chunks.

        Args:
            text: The raw text to split.

        Raises:
            ChunkingError: If chunking fails for any reason.
        """
        try:
            return await self._chunk(text)
        except Exception as e:
            raise ChunkingError(chunker=type(self).__name__) from e

    @abc.abstractmethod
    async def _chunk(self, text: str) -> list[PreviewChunk]:
        """Split `text` into preview chunks, preserving order.

        `chunk` translates any error into `ChunkingError`, so implementations
        need not wrap exceptions themselves.
        """
