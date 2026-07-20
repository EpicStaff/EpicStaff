import os
from typing import List, Optional

import httpx

from .base_embedder import BaseEmbedder
from ._http_retry import request_with_retry

TOGETHER_API_URL = "https://api.together.xyz/v1/embeddings"

# Mirrors the Together SDK's default retry policy (together/constants.py and
# together/abstract/api_requestor.py): retries on connection/timeout errors
# and on 429/5xx responses, with exponential backoff (INITIAL_RETRY_DELAY=0.5s,
# MAX_RETRY_DELAY=8.0s). The SDK default is 5 retries (6 attempts); this is
# simplified to 5 total attempts.
_MAX_ATTEMPTS = 5
_RETRYABLE_STATUSES = frozenset({429, *range(500, 600)})
_TRANSIENT_EXCEPTIONS = (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout)


class TogetherAIEmbedder(BaseEmbedder):
    def __init__(self, api_key: Optional[str] = None, model_name: Optional[str] = None):
        # dims=768
        self.model_name = model_name or "togethercomputer/m2-bert-80M-32k-retrieval"
        self.api_key = api_key or os.getenv("TOGETHER_API_KEY")
        if not self.api_key:
            raise ValueError(
                "Cohere API key must be provided via argument or 'TOGETHER_API_KEY' environment variable."
            )

    def embed(self, text: str) -> List[float]:
        """
        Generate an embedding for the given text using TogetherAI.

        Args:
            text (str): The text to embed.

        Returns:
            List[float]: The embedding vector.
        """
        text = text.replace("\n", " ")
        response = request_with_retry(
            lambda: httpx.post(
                TOGETHER_API_URL,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={"input": [text], "model": self.model_name},
                timeout=600,
            ),
            max_attempts=_MAX_ATTEMPTS,
            retryable_statuses=_RETRYABLE_STATUSES,
            transient_exceptions=_TRANSIENT_EXCEPTIONS,
        )
        response.raise_for_status()
        data = response.json()

        return data["data"][0]["embedding"]
