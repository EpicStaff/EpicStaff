from __future__ import annotations

import httpx
from loguru import logger
from pydantic import TypeAdapter

from shared.models.knowledge import (
    GraphRagSearchConfig,
    NaiveRagSearchConfig,
    RagSearchConfig,
)
from shared.models.knowledge_new import FoundChunk, SearchConfig

from app.knowledge.target import KnowledgeSearchTarget

_SEARCH_CONFIG = TypeAdapter(SearchConfig)
_RESULT = TypeAdapter(list[FoundChunk] | str)


def _to_search_config(config: RagSearchConfig) -> dict:
    """Convert the agent-side (old) search config to the knowledge_new wire dict.

    Field names line up 1-to-1; validating against ``SearchConfig`` fails loudly
    here if that ever drifts, instead of surfacing as a 4xx from knowledge_new.
    """
    if isinstance(config, NaiveRagSearchConfig):
        raw = {"rag_strategy": "naive", **config.model_dump(exclude={"rag_type"})}
    else:
        assert isinstance(config, GraphRagSearchConfig)
        params = config.search_params
        raw = {
            "rag_strategy": "graph",
            "method": params.search_method,
            **params.model_dump(exclude={"search_method"}),
        }
    return _SEARCH_CONFIG.validate_python(raw).model_dump(mode="json")


class KnowledgeClient:
    def __init__(self, base_url: str, timeout: float = 10.0) -> None:
        self._base_url = base_url
        self._default_timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def start(self) -> None:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._base_url, timeout=self._default_timeout
            )
            logger.info("KnowledgeClient started, base_url={}", self._base_url)

    async def stop(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
            logger.info("KnowledgeClient stopped")

    async def search(
        self, target: KnowledgeSearchTarget, query: str, *, timeout: float
    ) -> list[FoundChunk] | str:
        assert (
            self._client is not None
        ), "KnowledgeClient.start() must be called before search()"

        response = await self._client.post(
            f"rags/{target.rag_type}/{target.rag_id}/search/",
            json={
                "query": query,
                "search_config": _to_search_config(target.search_config),
                "embedding_api_key": target.embedder_api_key,
                "llm_api_key": target.llm_api_key,
            },
            timeout=timeout,
        )
        response.raise_for_status()
        return _RESULT.validate_python(response.json()["result"])
