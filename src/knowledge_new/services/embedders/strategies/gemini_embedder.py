from google import genai

from models import EmbeddingConfig
from services.embedders.base import AbstractEmbedder


class GeminiEmbedder(AbstractEmbedder):

    def __init__(self, config: EmbeddingConfig):
        super().__init__(config)
        self.api_key = self.config.api_key
        self.model = self.config.model
        self.client = genai.Client(api_key=self.api_key)

    async def _embed(self, text: str) -> list[float]:
        text = text.replace("\n", " ")
        response = await self.client.aio.models.embed_content(
            contents=text,
            model=self.model,
        )
        result = response.embeddings
        if result and result[0].values:
            return result[0].values
        return []
