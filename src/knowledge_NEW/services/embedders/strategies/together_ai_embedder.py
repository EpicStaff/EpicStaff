from together import AsyncTogether

from error_handler import handle_error
from errors import EmbeddingError
from models import EmbeddingConfig
from services.embedders.base import AbstractEmbedder


class TogetherAIEmbedder(AbstractEmbedder):
    """Together AI-backed text embedder."""

    def __init__(self, config: EmbeddingConfig):
        super().__init__(config)
        self.api_key = self.config.api_key
        self.model = self.config.model
        self.client = AsyncTogether(api_key=self.api_key)

    async def embed(self, text: str) -> list[float]:
        """Embed `text` via a single Together AI embeddings request.

        Returns:
            The embedding vector, or an empty list when the response is empty.

        Raises:
            EmbeddingError: If the request fails.
        """
        with handle_error(Exception, EmbeddingError, text, self):
            text = text.replace("\n", " ")
            response = await self.client.embeddings.create(
                input=[text],
                model=self.model,
            )
            result = response.data
            if result:
                return result[0].embedding
            return []
