from collections.abc import Callable
from typing import Any, ClassVar, Optional

import settings
from clients import KnowledgeClient
from clients.errors import ClientTimeoutError
from langgraph.types import StreamWriter
from loguru import logger
from models.graph_models import GraphMessage
from pydantic import TypeAdapter
from services.graph.events import StopEvent
from services.redis_service import RedisService
from src.shared.enums.knowledge_new import RAGStrategy
from src.shared.models import (
    FoundChunk,
    GraphSearchConfig,
    NaiveSearchConfig,
    SearchConfig,
    SearchRequest,
)


class RagSearchConfigFactory:
    """
    Factory class to build RAG search configs from dict based on rag_type.
    """

    _configs: ClassVar[dict[str, Callable]] = {
        "naive": NaiveSearchConfig.model_validate,
        "graph": TypeAdapter(GraphSearchConfig).validate_python,
    }

    _timeouts: ClassVar[dict[str, float]] = {
        "naive": settings.NAIVE_RAG_SEARCH_TIMEOUT,
        "graph": settings.GRAPH_RAG_SEARCH_TIMEOUT,
    }

    @classmethod
    def build(cls, rag_type: str, config_dict: dict[str, Any]) -> SearchConfig:
        """
        Build appropriate SearchConfig based on rag_type.

        Args:
            rag_type: Type of RAG ("naive", "graph", etc.)
            config_dict: Dict with RAG-specific parameters

        Returns:
            Appropriate SearchConfig subclass instance
        """
        config_class = cls._configs.get(rag_type)
        if not config_class:
            raise ValueError(
                f"Unsupported RAG type: {rag_type}. Supported types: {list(cls._configs.keys())}"
            )

        if rag_type == "naive":
            # naive config is flat — no search_params nesting and no method discriminator
            data = {k: v for k, v in config_dict.items() if k != "rag_type"}
            data["rag_strategy"] = rag_type
            return config_class(data)

        # graph: params nested under search_params, discriminated by search_method
        search_params = config_dict["search_params"]
        data = {k: v for k, v in search_params.items() if k != "search_method"}
        data["rag_strategy"] = rag_type
        data["method"] = search_params["search_method"]

        return config_class(data)

    @classmethod
    def get_timeout(cls, rag_type: str) -> int:
        """
        Get timeout for a given RAG type.
        """
        return cls._timeouts.get(rag_type, settings.DEFAULT_RAG_SEARCH_TIMEOUT)


class KnowledgeSearchService:
    """
    Service for searching knowledge using different RAG implementations.
    """

    def __init__(
        self,
        redis_service: RedisService,
        rag_embedder_api_key: str | None = None,
        rag_llm_api_key: str | None = None,
    ):
        self.redis_service = redis_service
        self.rag_embedder_api_key = rag_embedder_api_key
        self.rag_llm_api_key = rag_llm_api_key

    def search_knowledges(
        self,
        sender: str,
        knowledge_collection_id: int,
        rag_type_id: str,
        query: str,
        rag_search_config: dict[str, Any],
        stop_event: StopEvent | None = None,
        timeout: int | None = None,
        rag_embedder_api_key: str | None = None,
        rag_llm_api_key: str | None = None,
        writer: Optional["StreamWriter"] = None,
        session_id: int | None = None,
        node_name: str | None = None,
        execution_order: int | None = None,
    ) -> list[str]:
        """
        Search knowledge using specified RAG implementation.

        Args:
            sender: Identifier of the sender
            rag_type_id: RAG type and ID in format "rag_type:id" (e.g., "naive:6")
            query: Search query text
            rag_search_config: RAG-specific search parameters dict
            stop_event: Optional event to stop execution
            timeout: Timeout in seconds. If None, resolved automatically by rag_type.
            writer: Stream writer to emit the `extracted_chunks` graph message to.
                If None, no message is emitted.
            session_id: Session the search was run for. Only used when `writer` is set.
            node_name: Name of the calling node. Only used when `writer` is set.
            execution_order: Execution order of the calling node. Only used when
                `writer` is set.

        Returns:
            List of knowledge results (strings)
        """

        rag_type, rag_id = self._parse_rag_type_id(rag_type_id)

        if timeout is None:
            timeout = RagSearchConfigFactory.get_timeout(rag_type)

        search_config = RagSearchConfigFactory.build(rag_type, rag_search_config)

        request = SearchRequest(rag_id=rag_id, query=query, search_config=search_config)

        resolved_embedder_key = (
            rag_embedder_api_key if rag_embedder_api_key is not None else self.rag_embedder_api_key
        )
        resolved_llm_key = rag_llm_api_key if rag_llm_api_key is not None else self.rag_llm_api_key

        try:
            with KnowledgeClient() as client:
                result = client.search(
                    strategy=RAGStrategy(rag_type),
                    rag_id=rag_id,
                    query=query,
                    search_config=search_config,
                    timeout=timeout,
                    embedding_api_key=resolved_embedder_key,
                    llm_api_key=resolved_llm_key,
                )
        except ClientTimeoutError as e:
            raise TimeoutError(
                f"Knowledge search timeout for {rag_type_id} after {timeout}s"
            ) from e

        logger.info(
            "Knowledge search completed rag_id=%s sender=%s query=%r",
            rag_id,
            sender,
            query,
        )

        if writer is not None:
            self._add_knowledges_to_graph_message(
                request=request,
                result=result,
                collection_id=knowledge_collection_id,
                writer=writer,
                session_id=session_id,
                node_name=node_name,
                execution_order=execution_order,
            )

        if isinstance(result, str):
            return [result]
        return [chunk.text for chunk in result]

    @staticmethod
    def _parse_rag_type_id(rag_type_id: str) -> tuple[str, int]:
        """
        Parse rag_type_id string into type and ID.

        Args:
            rag_type_id: String in format "rag_type:id" (e.g., "naive:6")

        Returns:
            Tuple of (rag_type, rag_id)
        """
        try:
            rag_type, rag_id_str = rag_type_id.split(":", 1)
            rag_id = int(rag_id_str)
            return rag_type, rag_id
        except (ValueError, AttributeError) as e:
            raise ValueError(
                f"Invalid rag_type_id format: '{rag_type_id}'. "
                f"Expected format: 'rag_type:id' (e.g., 'naive:6')"
            ) from e

    @staticmethod
    def _add_knowledges_to_graph_message(
        request: SearchRequest,
        result: list[FoundChunk] | str,
        collection_id: int,
        writer: "StreamWriter",
        session_id: int | None,
        node_name: str | None,
        execution_order: int | None,
    ) -> None:
        if isinstance(result, str):
            chunks = [result]
        else:
            chunks = [c.model_dump() for c in result]

        knowledge_results_data = {
            "message_type": "extracted_chunks",
            "collection_id": collection_id,
            "retrieved_chunks": len(chunks),
            "knowledge_query": request.query,
            "rag_search_config": request.search_config.model_dump(),
            "chunks": chunks,
            "token_usage": {},  # not yet in new contract thats why empty
        }
        graph_message = GraphMessage(
            session_id=session_id,
            name=node_name,
            execution_order=execution_order,
            message_data=knowledge_results_data,
        )
        writer(graph_message)
