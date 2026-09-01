import os
from .base_embedder import BaseEmbedder
from openai import OpenAI


class OpenAIEmbedder(BaseEmbedder):
    def __init__(self, api_key, model_name, base_url: str | None = None):
        self.model_name = model_name or "text-embedding-3-small"

        api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.client = OpenAI(api_key=api_key, base_url=base_url)

    def embed(self, text: str) -> dict:
        """
        Get the embedding for the given text using OpenAI.

        Args:
            text (str): The text to embed.

        Returns:
            list: The embedding vector.
        """
        text = text.replace("\n", " ")
        response = self.client.embeddings.create(input=[text], model=self.model_name)

        return {
            "embedding": response.data[0].embedding,
            "token_usage": response.usage.model_dump(),
        }
