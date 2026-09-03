from typing import List, Optional

import httpx

from .base_embedder import BaseEmbedder
from ._http_retry import request_with_retry

import settings

COHERE_API_URL = "https://api.cohere.com/v2/embed"

# Mirrors the cohere-python SDK's default retry policy (cohere/core/http_client.py):
# `max_retries` defaults to 2 (so 3 total attempts) when no request_options
# override is passed, retrying on 408/409/429 and 5xx responses only (the SDK
# does not retry on connection/timeout exceptions), with exponential backoff
# (INITIAL_RETRY_DELAY_SECONDS=1.0, MAX_RETRY_DELAY_SECONDS=60.0; the SDK also
# adds jitter, which is omitted here for simplicity).
_MAX_ATTEMPTS = 3
_RETRYABLE_STATUSES = frozenset({408, 409, 429, *range(500, 600)})


class CohereEmbedder(BaseEmbedder):
    def __init__(self, api_key: Optional[str] = None, model_name: Optional[str] = None):
        # dims=1536
        self.model_name = model_name or "embed-v4.0"
        self.input_type = "search_query"
        self.api_key = api_key or settings.COHERE_API_KEY
        if not self.api_key:
            raise ValueError(
                "Cohere API key must be provided via argument or 'COHERE_API_KEY' environment variable."
            )

    def embed(self, text: str) -> List[float]:
        """
        Generate an embedding for the given text using Cohere.

        Args:
            text (str): The text to embed.

        Returns:
            List[float]: The embedding vector.
        """
        text = text.replace("\n", " ")
        response = request_with_retry(
            lambda: httpx.post(
                COHERE_API_URL,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "texts": [text],
                    "model": self.model_name,
                    "input_type": self.input_type,
                    "embedding_types": ["float"],
                },
                timeout=300,
            ),
            max_attempts=_MAX_ATTEMPTS,
            retryable_statuses=_RETRYABLE_STATUSES,
            initial_delay=1.0,
            max_delay=60.0,
        )
        response.raise_for_status()
        data = response.json()

        return data["embeddings"]["float"][0]
