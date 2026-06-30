from models import EmbeddingConfig
from openai import AsyncOpenAI
from services.embedders.base import AbstractEmbedder


class OpenAIEmbedder(AbstractEmbedder):
    def __init__(self, config: EmbeddingConfig):
        super().__init__(config)
        self.api_key = self.config.api_key
        self.model = self.config.model
        self.client = AsyncOpenAI(api_key=self.api_key)

    async def _embed(self, text: str) -> list[float]:
        text = text.replace("\n", " ")
        response = await self.client.embeddings.create(input=[text], model=self.model)
        result = response.data
        if result:
            return result[0].embedding
        return []
