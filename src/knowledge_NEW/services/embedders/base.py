import abc

from models import EmbeddingConfig


class AbstractEmbedder(abc.ABC):
    """Abstract base for turning text into an embedding vector.

    Subclasses must implement `embed`; it is the only contract a concrete
    embedder has to fulfil.
    """

    def __init__(self, config: EmbeddingConfig):
        self.config = config

    @abc.abstractmethod
    async def embed(self, text: str) -> list[float]:
        """Return an embedding vector for `text`.

        Implementations must return an empty list when the provider yields no
        embedding, and raise `EmbeddingError` when the text cannot be embedded.

        Args:
            text: The text to embed.

        Returns:
            The embedding vector, or an empty list when none is produced.
        """
