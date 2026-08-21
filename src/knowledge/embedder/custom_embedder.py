import json
from typing import List
import requests
import os

from .base_embedder import BaseEmbedder


class CustomEmbedder(BaseEmbedder):
    def __init__(
        self, api_key: str = None, model_name: str = None, base_url: str = None
    ):
        """Initialize the embedder."""
        self.base_url = base_url or os.getenv("CUSTOM_EMBED_BASE_URL")
        self.api_key = api_key or os.getenv("CUSTOM_EMBED_API_KEY")
        self.model_name = model_name or "nomic-embed-text-v2-moe"
        self.endpoint = f"{self.base_url}"

    def embed(self, text: str) -> List[float]:
        """Get embedding for text."""
        text = text.replace("\n", " ")
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        raw_headers = os.environ.get("EMBEDDING_HEADERS")
        if raw_headers:
            extra_headers = json.loads(raw_headers)
            headers.update(extra_headers)

        response = requests.post(
            self.endpoint,
            headers=headers,
            json={"model": self.model_name, "input": [text]},
        )
        response.raise_for_status()
        payload = response.json()
        # Hotfix specifically for OpenAI-compatible endpoints ({"data": [{"embedding": [...]}]})
        if "data" in payload:
            return payload["data"][0]["embedding"]
        return payload["embeddings"][0]
