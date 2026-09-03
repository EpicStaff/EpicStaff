from typing import List, Optional

import httpx

from .base_embedder import BaseEmbedder

import settings

MISTRAL_API_URL = "https://api.mistral.ai/v1/embeddings"


class MistralEmbedder(BaseEmbedder):
    def __init__(self, api_key: Optional[str] = None, model_name: Optional[str] = None):
        # dims=1024
        self.model_name = model_name or "mistral-embed"
        self.api_key = api_key or settings.MISTRAL_API_KEY
        if not self.api_key:
            raise ValueError(
                "Cohere API key must be provided via argument or 'MISTRAL_API_KEY' environment variable."
            )

    def embed(self, text: str) -> List[float]:
        """
        Generate an embedding for the given text using MistralAI.

        Args:
            text (str): The text to embed.

        Returns:
            List[float]: The embedding vector.
        """
        text = text.replace("\n", " ")
        # No explicit timeout here on purpose: the removed mistralai SDK built
        # its httpx.Client() without a timeout override either, so it inherited
        # httpx's 5s default. Not passing `timeout=` below preserves that exact
        # behavior (unlike together_ai.py/cohere.py, whose SDKs did set their
        # own longer defaults, which we replicate explicitly).
        response = httpx.post(
            MISTRAL_API_URL,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={"input": [text], "model": self.model_name},
        )
        response.raise_for_status()
        data = response.json()

        return data["data"][0]["embedding"]
