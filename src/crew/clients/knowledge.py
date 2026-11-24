from typing import Any

import httpx
from foundation.transport.http import AsyncClient
from src.shared.enums.knowledge_new import RAGStrategy
from src.shared.models import FoundChunk, SearchConfig, SearchOutcome, SearchUsage

# knowledge_new's uvicorn closes a keep-alive connection after 5 s idle (its default). Ours must
# expire first: a request sent on a connection the server is closing at that moment is reset
# and surfaces as httpx.ReadError.
KEEPALIVE_EXPIRY_SECONDS = 2.0


class KnowledgeClient(AsyncClient):
    """Async client for knowledge_new's search API, shared by every session crew runs.

    Built like any httpx client (`base_url`, `transport`, ...); the connection limits are
    fixed here because they follow from how knowledge_new serves connections.
    """

    def __init__(self, *, base_url: str, **httpx_options) -> None:
        super().__init__(
            base_url=base_url,
            limits=httpx.Limits(
                max_connections=100,
                max_keepalive_connections=20,
                keepalive_expiry=KEEPALIVE_EXPIRY_SECONDS,
            ),
            **httpx_options,
        )

    async def search_with_usage(
        self,
        strategy: RAGStrategy,
        rag_id: int,
        query: str,
        search_config: SearchConfig,
        timeout: float,
        embedding_api_key: str,
        llm_api_key: str | None,
        embedding_extra_headers: dict[str, str] | None = None,
        llm_extra_headers: dict[str, str] | None = None,
        embedding_connection: dict[str, str] | None = None,
        embedding_parameters: dict[str, Any] | None = None,
        llm_connection: dict[str, str] | None = None,
        llm_parameters: dict[str, Any] | None = None,
    ) -> SearchOutcome:
        """Search a RAG, returning its result with the embedding usage knowledge_new reports.

        Raises:
            ClientTimeoutError: knowledge_new did not answer within `timeout` seconds.
            ClientConnectionError: knowledge_new could not be reached.
            ClientHTTPStatusError: knowledge_new answered with a non-2xx status.
        """
        response = await self.post(
            f"rags/{strategy}/{rag_id}/search/",
            json={
                "query": query,
                "search_config": search_config.model_dump(mode="json"),
                "embedding_api_key": embedding_api_key,
                "llm_api_key": llm_api_key,
                "embedding_extra_headers": embedding_extra_headers or {},
                "llm_extra_headers": llm_extra_headers or {},
                "embedding_connection": embedding_connection or {},
                "embedding_parameters": embedding_parameters or {},
                "llm_connection": llm_connection or {},
                "llm_parameters": llm_parameters or {},
            },
            timeout=timeout,
        )
        body = response.json()
        result = body["result"]
        if isinstance(result, list):
            result = [FoundChunk(**d) for d in result]
        return SearchOutcome(result=result, usage=SearchUsage(**body.get("usage", {})))
