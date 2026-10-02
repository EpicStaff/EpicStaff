from collections.abc import Callable
from typing import Any, ClassVar

from domain.models.realtime_tool import RealtimeTool, ToolParameters
from loguru import logger
from src.shared.knowledge.client import KnowledgeClient
from src.shared.knowledge.target import KnowledgeSearchTarget
from src.shared.models import (
    GraphRagSearchConfig,
    NaiveRagSearchConfig,
    RagSearchConfig,
)

from .base_tool_executor import BaseToolExecutor

DEFAULT_KNOWLEDGE_SEARCH_TIMEOUT = 30.0


class KnowledgeSearchToolExecutor(BaseToolExecutor):
    def __init__(
        self,
        knowledge_collection_id: int,
        rag_type_id: str,
        rag_search_config: dict[str, Any],
        knowledge_client: KnowledgeClient,
        rag_embedder_api_key: str | None = None,
        rag_llm_api_key: str | None = None,
    ):
        super().__init__(tool_name="knowledge_tool")
        self.rag_embedder_api_key = rag_embedder_api_key
        self.rag_llm_api_key = rag_llm_api_key
        self.knowledge_collection_id = knowledge_collection_id
        self.knowledge_client = knowledge_client
        self._realtime_model = self._gen_knowledge_realtime_tool_model()
        self.rag_type, self.rag_id = self._parse_rag_type_id(rag_type_id)
        self.rag_search_config = RagConfigBuilder.build(self.rag_type, rag_search_config)

    async def execute(self, **kwargs) -> str:
        query = kwargs.get("query")
        if query is None:
            return ""

        target = KnowledgeSearchTarget(
            collection_id=self.knowledge_collection_id,
            rag_id=self.rag_id,
            rag_type=self.rag_type,
            search_config=self.rag_search_config,
            embedder_api_key=self.rag_embedder_api_key,
            llm_api_key=self.rag_llm_api_key,
        )

        try:
            result = await self.knowledge_client.search(
                target, query, timeout=DEFAULT_KNOWLEDGE_SEARCH_TIMEOUT
            )
        except Exception as error:
            logger.warning("Knowledge search failed rag_id={} error={}", self.rag_id, error)
            return f"Knowledge search failed: {error}"

        if isinstance(result, str):
            knowledges = result
        else:
            knowledges = "\n\n".join(chunk.text for chunk in result)

        return f"\nUse this information for answer: {knowledges}" if knowledges else ""

    def _gen_knowledge_realtime_tool_model(self) -> RealtimeTool:
        tool_parameters = ToolParameters(
            properties={"query": {"type": "string", "description": "Search query in document"}},
            required=["query"],
        )
        return RealtimeTool(
            name=self.tool_name,
            description="Use this tool every time user asks anything",
            parameters=tool_parameters,
        )

    async def get_realtime_tool_model(self) -> RealtimeTool:
        return self._realtime_model

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


class RagConfigBuilder:
    """
    Factory class to build RAG search configs from dict based on rag_type.
    """

    _config_builders: ClassVar[dict[str, Callable]] = {
        "naive": lambda config: NaiveRagSearchConfig(**config),
        "graph": lambda config: GraphRagSearchConfig(**config),
        # Future RAG types
    }

    @classmethod
    def build(cls, rag_type: str, config_dict: dict[str, Any]) -> RagSearchConfig:
        """
        Build appropriate RagSearchConfig based on rag_type.

        Args:
            rag_type: Type of RAG ("naive", "graph", etc.)
            config_dict: Dict with RAG-specific parameters

        Returns:
            Appropriate RagSearchConfig subclass instance
        """
        builder = cls._config_builders.get(rag_type)
        if not builder:
            raise ValueError(
                f"Unsupported RAG type: {rag_type}. "
                f"Supported types: {list(cls._config_builders.keys())}"
            )

        return builder(config_dict)
