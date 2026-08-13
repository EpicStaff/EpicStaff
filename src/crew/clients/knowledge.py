from typing import Literal

import httpx

from src.shared.enums.knowledge_new import RAGStrategy
from src.shared.models import FoundChunk, SearchConfig

from clients.errors import (
    ClientBadGatewayError,
    ClientNotAvailableError,
    ClientTimeoutError,
    ClientValidationError,
)


class KnowledgeClient:
    HOST = "http://knowledge_new:8100"

    def __init__(self, host: str = HOST):
        self._client = httpx.Client(base_url=host)

    def __enter__(self) -> "KnowledgeClient":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def search(
        self,
        strategy: RAGStrategy,
        rag_id: int,
        query: str,
        search_config: SearchConfig,
        timeout: float,
    ) -> list[FoundChunk] | str:
        response = self._request(
            method="post",
            url=f"rags/{strategy}/{rag_id}/search/",
            json={
                "query": query,
                "search_config": search_config.model_dump(mode="json"),
            },
            timeout=timeout,
        )
        result = response.json()["result"]
        if isinstance(result, list):
            return [FoundChunk(**d) for d in result]
        return result

    def _request(
        self,
        method: Literal["get", "post", "put", "patch", "delete"],
        url: str,
        json: dict,
        timeout: float,
    ) -> httpx.Response:
        try:
            response = getattr(self._client, method)(url=url, json=json, timeout=timeout)
        except httpx.TimeoutException as e:
            raise ClientTimeoutError("Knowledge service timed out.") from e
        except httpx.RequestError as e:
            raise ClientNotAvailableError("Knowledge service is unreachable.") from e

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            if response.status_code >= 500:
                raise ClientBadGatewayError(response.text) from e
            raise ClientValidationError(response.text) from e

        return response
