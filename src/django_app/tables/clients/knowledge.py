from typing import Literal

import httpx
from loguru import logger

from src.shared.enums.knowledge_new import RAGStrategy
from src.shared.models.knowledge_new import ChunkingConfig

from tables.clients.errors import (
    ClientBadGatewayError,
    ClientNotAvailableError,
    ClientTimeoutError,
    ClientValidationError,
)


class KnowledgeClient:
    HOST = "http://knowledge_new:8100"

    def __init__(self, host: str = HOST, timeout: float = 10.0):
        self._client = httpx.Client(base_url=host, timeout=timeout)

    def __enter__(self) -> "KnowledgeClient":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def index(
        self,
        strategy: RAGStrategy,
        rag_id: int,
        document_ids: frozenset[int],
        embedding_api_key: str,
        llm_api_key: str | None = None,
    ) -> None:
        self._request(
            method="post",
            url=f"rags/{strategy}/{rag_id}/index/",
            json={
                "document_ids": list(document_ids),
                "embedding_api_key": embedding_api_key,
                "llm_api_key": llm_api_key,
            },
        )

    def prechunk(
        self,
        strategy: RAGStrategy,
        rag_id: int,
        document_id: int,
        chunking_config: ChunkingConfig,
    ) -> None:
        self._request(
            method="post",
            url=f"rags/{strategy}/{rag_id}/prechunk/",
            json={
                "document_id": document_id,
                "chunking_config": chunking_config.model_dump(mode="json"),
            },
        )

    def cancel(
        self,
        strategy: RAGStrategy,
        rag_id: int,
        operation: Literal["index", "prechunk"],
    ) -> None:
        self._request(
            method="delete", url=f"rags/{strategy}/{rag_id}/cancel/{operation}/"
        )

    def delete(self, strategy: RAGStrategy, rag_id: int):
        self._request(method="delete", url=f"rags/{strategy}/{rag_id}/")

    def metrics(self, strategy: RAGStrategy, rag_id: int) -> dict:
        response = self._request(method="get", url=f"rags/{strategy}/{rag_id}/metrics/")
        return response.json()

    def _request(
        self, method: str, url: str, *, json: dict | None = None
    ) -> httpx.Response:
        try:
            response = self._client.request(method, url, json=json)
        except httpx.TimeoutException as e:
            raise ClientTimeoutError("Knowledge service timed out.") from e
        except httpx.RequestError as e:
            logger.exception("KNOWLEDGE CLIENT ERROR: {}", e)
            raise ClientNotAvailableError("Knowledge service is unreachable.") from e

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            if response.status_code >= 500:
                raise ClientBadGatewayError(response.text) from e
            raise ClientValidationError(response.text) from e

        return response
