from typing import Literal, Self

import httpx
from loguru import logger
from src.shared.enums.knowledge_new import RAGStrategy
from src.shared.models.knowledge_new import ChunkingConfig

from tables.clients.errors import (
    ClientBadGatewayError,
    ClientNotAvailableError,
    ClientResourceNotFoundError,
    ClientTimeoutError,
    ClientValidationError,
)


class KnowledgeClient:
    HOST = "http://knowledge_new:8100"

    def __init__(self, host: str = HOST, timeout: float = 10.0):
        self._client = httpx.Client(base_url=host, timeout=timeout)

    def __enter__(self) -> Self:
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
        embedding_extra_headers: dict[str, str] | None = None,
        llm_extra_headers: dict[str, str] | None = None,
    ) -> None:
        self._request(
            method="post",
            url=f"rags/{strategy}/{rag_id}/index/",
            json={
                "document_ids": list(document_ids),
                "embedding_api_key": embedding_api_key,
                "llm_api_key": llm_api_key,
                "embedding_extra_headers": embedding_extra_headers or {},
                "llm_extra_headers": llm_extra_headers or {},
            },
        )

    def index_estimate(
        self,
        strategy: RAGStrategy,
        rag_id: int,
        document_ids: frozenset[int],
        chunking_overrides: dict[int, ChunkingConfig] | None = None,
    ) -> dict:
        response = self._request(
            method="post",
            url=f"rags/{strategy}/{rag_id}/index-estimate/",
            json={
                "document_ids": list(document_ids),
                "chunking_overrides": [
                    {
                        "document_id": document_id,
                        "chunking_config": chunking_config.model_dump(mode="json"),
                    }
                    for document_id, chunking_config in (chunking_overrides or {}).items()
                ],
            },
        )
        return response.json()

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
        self._request(method="delete", url=f"rags/{strategy}/{rag_id}/cancel/{operation}/")

    def delete(self, strategy: RAGStrategy, rag_id: int):
        self._request(method="delete", url=f"rags/{strategy}/{rag_id}/")

    def metrics(self, strategy: RAGStrategy, rag_id: int) -> dict:
        response = self._request(method="get", url=f"rags/{strategy}/{rag_id}/metrics/")
        return response.json()

    def get_visualization(
        self,
        rag_id: int,
        max_entities: int | None = None,
        search: str | None = None,
    ) -> dict:
        """Fetch graph visualization data for a graph RAG."""
        url = f"rags/graph/{rag_id}/visualization/"
        params: dict[str, str | int] = {}
        if max_entities is not None:
            params["max_entities"] = max_entities
        if search:
            params["search"] = search
        response = self._request(method="get", url=url, params=params)
        return response.json()

    def get_entity_detail(self, rag_id: int, entity_id: str) -> dict:
        """Fetch the description of a single entity from the graph index."""
        response = self._request(
            method="get", url=f"rags/graph/{rag_id}/entity/{entity_id}/"
        )
        return response.json()

    def get_relationship_detail(self, rag_id: int, relationship_id: str) -> dict:
        """Fetch the description of a single relationship from the graph index."""
        response = self._request(
            method="get", url=f"rags/graph/{rag_id}/relationship/{relationship_id}/"
        )
        return response.json()

    def get_table_data(
        self,
        rag_id: int,
        table_name: str,
        page: int = 1,
        page_size: int = 10,
        search: str | None = None,
    ) -> dict:
        """Fetch paginated parquet table data for a graph RAG."""
        url = f"rags/graph/{rag_id}/tables/{table_name}/"
        params: dict = {"page": page, "page_size": page_size}
        if search:
            params["search"] = search
        response = self._request(method="get", url=url, params=params)
        return response.json()

    def get_table_summary(self, rag_id: int) -> list[dict]:
        """Fetch the list of available tables with their row counts."""
        response = self._request(
            method="get", url=f"rags/graph/{rag_id}/table-summary/"
        )
        return response.json()

    def _request(
        self,
        method: str,
        url: str,
        *,
        json: dict | None = None,
        params: dict | None = None,
    ) -> httpx.Response:
        try:
            response = self._client.request(method, url, json=json, params=params)
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
            if response.status_code == 404:
                raise ClientResourceNotFoundError(response.text) from e
            raise ClientValidationError(response.text) from e

        return response
