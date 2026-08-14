from typing import Literal

import httpx

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
    ) -> None:
        self._request(
            method="post",
            url=f"rags/{strategy}/{rag_id}/index/",
            json={"document_ids": list(document_ids)},
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
        self._request(method="delete", url=f"rags/{strategy}/{rag_id}/{operation}/cancel/")

    def _request(self, method: str, url: str, *, json: dict | None = None) -> httpx.Response:
        try:
            response = self._client.request(method, url, json=json)
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
