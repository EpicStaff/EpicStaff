from cohere import AsyncClient, EmbeddingsFloatsEmbedResponse
from models import EmbeddingConfig
from services.embedders.base import AbstractEmbedder


class CohereEmbedder(AbstractEmbedder):
    def __init__(self, config: EmbeddingConfig):
        super().__init__(config)
        self.api_key = self.config.api_key
        self.model = self.config.model
        self.client = AsyncClient(self.api_key)

    async def _embed(self, text: str) -> list[float]:
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
