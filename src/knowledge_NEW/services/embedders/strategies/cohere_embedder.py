from cohere import AsyncClient, EmbeddingsFloatsEmbedResponse

from error_handler import handle_error
from errors import EmbeddingError
from models import EmbeddingConfig
from services.embedders.base import AbstractEmbedder


class CohereEmbedder(AbstractEmbedder):
    """Cohere-backed text embedder."""

    def __init__(self, config: EmbeddingConfig):
        super().__init__(config)
        self.api_key = self.config.api_key
        self.model = self.config.model
        self.client = AsyncClient(self.api_key)

    async def embed(self, text: str) -> list[float]:
        """Embed `text` via a single Cohere embeddings request.

        Returns:
            The embedding vector, or an empty list when the response is empty.

        Raises:
            EmbeddingError: If the request fails.
        """
        with handle_error(Exception, EmbeddingError, text, self):
            text = text.replace("\n", " ")
            response = await self.client.embed(
                texts=[text],
                model=self.model,
                input_type="search_query",
                embedding_types=["float"],
            )
            assert isinstance(response, EmbeddingsFloatsEmbedResponse)
            result = response.embeddings
            if result:
                return result[0]
            return []
