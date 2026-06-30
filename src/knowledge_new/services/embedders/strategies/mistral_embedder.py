from mistralai.client import Mistral
from models import EmbeddingConfig
from services.embedders.base import AbstractEmbedder


class MistralEmbedder(AbstractEmbedder):
    def __init__(self, config: EmbeddingConfig):
        super().__init__(config)
        self.api_key = self.config.api_key
        self.model = self.config.model
        self.client = Mistral(api_key=self.api_key)

    async def _embed(self, text: str) -> list[float]:
        text = text.replace("\n", " ")
        response = await self.client.embeddings.create_async(inputs=[text], model=self.model)
        result = response.data
        if result and result[0].embedding:
            return result[0].embedding
        return []
