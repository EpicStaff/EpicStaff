import abc

from models import ChunkingConfig, PreviewChunk


class AbstractChunker(abc.ABC):
    """Base class for text chunkers.

    Each implementation chunks raw text into `PreviewChunk` instances according
    to a `ChunkingConfig`; the chunking strategy and any extra configuration
    are owned by the implementation.
    """

    def __init__(self, config: ChunkingConfig):
        self.config = config

    @abc.abstractmethod
    async def chunk(self, text: str) -> list[PreviewChunk]:
        """Split `text` into `PreviewChunk` instances.

        Implementations must preserve order: chunks are returned in the order
        they appear in `text`.

        Args:
            text: The raw text to split.

        Returns:
            The chunks produced from `text`.

        Raises:
            ChunkingError: If the text cannot be chunked.
        """
