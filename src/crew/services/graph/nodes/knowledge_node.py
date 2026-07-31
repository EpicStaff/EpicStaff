import asyncio
from typing import Any

from langgraph.types import StreamWriter

from models.state import State
from services.graph.events import StopEvent
from services.graph.nodes import BaseNode
from services.knowledge_search_service import KnowledgeSearchService
from src.shared.models import RagSearchConfig


class KnowledgeNode(BaseNode):
    TYPE = "KNOWLEDGE"

    def __init__(
        self,
        session_id: int,
        node_name: str,
        stop_event: StopEvent,
        input_map: dict,
        output_variable_path: str | None,
        collection_id: int,
        rag_type_id: str,
        query: str,
        rag_search_config: RagSearchConfig | None,
        knowledge_search_service: KnowledgeSearchService,
    ):
        super().__init__(
            session_id=session_id,
            node_name=node_name,
            stop_event=stop_event,
            input_map=input_map,
            output_variable_path=output_variable_path,
        )
        self.collection_id = collection_id
        self.rag_type_id = rag_type_id
        self.query_template = query
        self.rag_search_config = rag_search_config
        self.knowledge_search_service = knowledge_search_service

    async def execute(
        self, state: State, writer: StreamWriter, execution_order: int, input_: Any
    ) -> str:
        query = self.query_template.format(**input_)
        # None = no per-node config rows → let the search service apply RAG defaults.
        rag_search_config = (
            self.rag_search_config.model_dump() if self.rag_search_config else {}
        )
        # search_knowledges blocks on a Redis pub/sub poll → offload off the event loop.
        chunks = await asyncio.to_thread(
            self.knowledge_search_service.search_knowledges,
            sender="node",
            knowledge_collection_id=self.collection_id,
            rag_type_id=self.rag_type_id,
            query=query,
            rag_search_config=rag_search_config,
            stop_event=self.stop_event,
        )
        return "\n\n".join(chunks)
