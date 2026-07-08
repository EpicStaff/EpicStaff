import abc
from http import HTTPStatus

from errors import EmbedderAuthError, EmbedderRateLimitError, EmbeddingError
from models import EmbeddingConfig
from utils import http_status


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
            raise self._as_embedding_error(e) from e

    def _as_embedding_error(self, exc: Exception) -> EmbeddingError:
        """Map a provider exception to the matching `EmbeddingError` subclass."""
        
        embedder = type(self).__name__
        name = type(exc).__name__.lower()
        status = http_status(exc)

        if status in (HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN) or any(
            token in name for token in ("authentication", "unauthorized", "permissiondenied")
        ):
            return EmbedderAuthError(embedder=embedder)
        if status == HTTPStatus.TOO_MANY_REQUESTS or any(
            token in name for token in ("ratelimit", "toomanyrequests")
        ):
            return EmbedderRateLimitError(embedder=embedder)
        return EmbeddingError(embedder=embedder)

    @abc.abstractmethod
    async def _embed(self, text: str) -> list[float]:
        """Return the embedding vector for `text`.

        `embed` translates any error into `EmbeddingError`, so implementations
        need not wrap exceptions themselves.
        """
