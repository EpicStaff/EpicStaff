import abc

from domain.errors import EmbeddingError
from domain.models import EmbeddingConfig


class AbstractEmbedder(abc.ABC):
    """Abstract base for turning text into an embedding vector."""

    def __init__(self, config: EmbeddingConfig):
        self.config = config

    async def embed(self, text: str) -> list[float]:
        """Embed `text` into a vector.

        Args:
            text: The text to embed.

        Raises:
            EmbeddingError: If embedding fails for any reason.
        """
        try:
            return await self._embed(text)
        except Exception as e:
            raise EmbeddingError(embedder=type(self).__name__) from e

    @abc.abstractmethod
    async def _embed(self, text: str) -> list[float]:
        """Return the embedding vector for `text`.

        `embed` translates any error into `EmbeddingError`, so implementations
        need not wrap exceptions themselves.
        """
