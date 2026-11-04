from collections.abc import Iterator, Mapping
from typing import BinaryIO, Literal, Self

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

_ARTIFACT_TIMEOUT = httpx.Timeout(600.0, connect=10.0)
_UPLOAD_CHUNK_SIZE = 1024 * 1024


class KnowledgeClient:
    HOST = "http://knowledge_new:8100"

    def __init__(
        self, host: str = HOST, timeout: float = 10.0, transport: httpx.BaseTransport | None = None
    ):
        self._client = httpx.Client(base_url=host, timeout=timeout, transport=transport)

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

    def _request(
        self,
        method: str,
        url: str,
        *,
        json: dict | None = None,
        content: Iterator[bytes] | None = None,
        timeout: httpx.Timeout | None = httpx.USE_CLIENT_DEFAULT,
    ) -> httpx.Response:
        try:
            response = self._client.request(
                method, url, json=json, content=content, timeout=timeout
            )
        except httpx.TimeoutException as e:
            raise ClientTimeoutError("Knowledge service timed out.") from e
        except httpx.RequestError as e:
            logger.exception("KNOWLEDGE CLIENT ERROR: {}", e)
            raise ClientNotAvailableError("Knowledge service is unreachable.") from e
        self._raise_for_status(response)
        return response

    def download_graph_artifacts(self, rag_id: int, destination: BinaryIO) -> None:
        """Write the tar of a completed graph RAG's index into `destination`, chunk by chunk."""
        try:
            with self._client.stream(
                "GET", f"rags/{RAGStrategy.GRAPH}/{rag_id}/artifacts/", timeout=_ARTIFACT_TIMEOUT
            ) as response:
                if response.is_error:
                    response.read()
                    self._raise_for_status(response)
                destination.writelines(response.iter_bytes())
        except httpx.TimeoutException as e:
            raise ClientTimeoutError("Knowledge service timed out.") from e
        except httpx.RequestError as e:
            logger.exception("KNOWLEDGE CLIENT ERROR: {}", e)
            raise ClientNotAvailableError("Knowledge service is unreachable.") from e

    def upload_graph_artifacts(
        self, rag_id: int, source: BinaryIO, document_id_map: Mapping[int, int]
    ) -> None:
        """Restore an exported index into the graph RAG, then give it this side's document ids.

        Args:
            document_id_map: New `GraphRagDocument` id for each id the index was exported with.
        """
        base_url = f"rags/{RAGStrategy.GRAPH}/{rag_id}/artifacts/"
        self._request(
            "put",
            base_url,
            content=iter(lambda: source.read(_UPLOAD_CHUNK_SIZE), b""),
            timeout=_ARTIFACT_TIMEOUT,
        )
        self._request(
            "post",
            f"{base_url}document-ids/",
            json={
                "document_id_map": {
                    str(old_id): new_id for old_id, new_id in document_id_map.items()
                }
            },
            timeout=_ARTIFACT_TIMEOUT,
        )

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            if response.status_code >= 500:
                raise ClientBadGatewayError(response.text) from e
            if response.status_code == 404:
                raise ClientResourceNotFoundError(response.text) from e
            raise ClientValidationError(response.text) from e
