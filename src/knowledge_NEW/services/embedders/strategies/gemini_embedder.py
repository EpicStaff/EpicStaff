from google import genai

from error_handler import handle_error
from errors import EmbeddingError
from models import EmbeddingConfig
from services.embedders.base import AbstractEmbedder


class GeminiEmbedder(AbstractEmbedder):
    """Gemini-backed text embedder."""

    def __init__(self, config: EmbeddingConfig):
        super().__init__(config)
        self.api_key = self.config.api_key
        self.model = self.config.model
        self.client = genai.Client(api_key=self.api_key)

    async def embed(self, text: str) -> list[float]:
        """Embed `text` via a single Gemini embeddings request.

        Returns:
            The embedding vector, or an empty list when the response is empty.

        Raises:
            EmbeddingError: If the request fails.
        """
        with handle_error(Exception, EmbeddingError, text, self):
            text = text.replace("\n", " ")
            response = await self.client.aio.models.embed_content(
                contents=text,
                model=self.model,
            )
            result = response.embeddings
            if result and result[0].values:
                return result[0].values
            return []
