from typing import List, Optional
from .base_embedder import BaseEmbedder

from google import genai

import settings


class GoogleGenAIEmbedder(BaseEmbedder):
    def __init__(self, api_key: Optional[str] = None, model_name: Optional[str] = None):
        self.api_key = api_key or settings.GOOGLE_API_KEY
        if not self.api_key:
            raise ValueError(
                "Google API key must be provided via argument or 'GOOGLE_API_KEY' environment variable."
            )
        # dims=768
        self.model_name = model_name or "models/text-embedding-004"
        self.client = genai.Client(api_key=self.api_key)

    def embed(self, text: str) -> List[float]:
        """
        Generate an embedding for the given text using Google Generative AI.

        Args:
            text (str): The text to embed.

        Returns:
            List[float]: The embedding vector.
        """
        text = text.replace("\n", " ")
        response = self.client.models.embed_content(
            model=self.model_name, contents=text
        )

        return response.embeddings[0]
