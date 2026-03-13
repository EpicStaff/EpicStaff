import asyncio
from typing import Dict, Any
from loguru import logger
from models.ai_models import RealtimeTool, ToolParameters
from services.redis_service import RedisService
from uuid import uuid4

from .base_tool_executor import BaseToolExecutor
from src.shared.models import (
    BaseKnowledgeSearchMessage,
    RagSearchConfig,
    NaiveRagSearchConfig,
    GraphRagSearchConfig,
)

import json


class KnowledgeSearchToolExecutor(BaseToolExecutor):
    def __init__(
        self,
        knowledge_collection_id: int,
        rag_type_id: str,
        rag_search_config: Dict[str, Any],
        redis_service: RedisService,
        knowledge_search_get_channel: str,
        knowledge_search_response_channel: str,
    ):
        super().__init__(tool_name="knowledge_tool")
        self.knowledge_search_get_channel = knowledge_search_get_channel
        self.knowledge_collection_id = knowledge_collection_id
        self.knowledge_search_response_channel = knowledge_search_response_channel
        self.redis_service = redis_service
        self._realtime_model = self._gen_knowledge_realtime_tool_model()
        self.rag_type, self.rag_id = self._parse_rag_type_id(rag_type_id)
        self.rag_search_config = RagConfigBuilder.build(
            self.rag_type, rag_search_config
        )

    async def execute(self, **kwargs) -> list[str]:
        query = kwargs.get("query")
        if query is None:
            return
        # TODO: wait for redis search
        pubsub = await self.redis_service.async_subscribe(
            channel=self.knowledge_search_response_channel
        )
        execution_uuid = str(uuid4())
        execution_message = BaseKnowledgeSearchMessage(
            collection_id=self.knowledge_collection_id,
            rag_id=self.rag_id,
            rag_type=self.rag_type,
            uuid=execution_uuid,
            query=query,
            rag_search_config=self.rag_search_config,
        )
        await self.redis_service.async_publish(
            channel=self.knowledge_search_get_channel,
            message=execution_message.model_dump(),
        )
        logger.info("Waiting for knowledges")
        while True:
            message = await pubsub.get_message(
                ignore_subscribe_messages=True, timeout=0.1
            )
            if not message:
                continue
            data = json.loads(message["data"])

            if data["uuid"] == execution_uuid:
                knowledges = "\n\n".join(data["results"])
                result = (
                    f"\nUse this information for answer: {knowledges}"
                    if knowledges
                    else ""
                )
                return result

            await asyncio.sleep(0.1)

    def _gen_knowledge_realtime_tool_model(self) -> RealtimeTool:
        tool_parameters = ToolParameters(
            properties={
                "query": {"type": "string", "description": "Search query in document"}
            },
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

    _config_builders = {
        "naive": lambda config: NaiveRagSearchConfig(**config),
        "graph": lambda config: GraphRagSearchConfig(**config),
        # Future RAG types
    }

    @classmethod
    def build(cls, rag_type: str, config_dict: Dict[str, Any]) -> RagSearchConfig:
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
