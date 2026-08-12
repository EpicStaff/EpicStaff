import asyncio
from typing import Any

from langgraph.types import StreamWriter

from models.state import State
from services.graph.events import StopEvent
from services.graph.exceptions import KnowledgeSearchError
from services.graph.nodes import BaseNode
from services.knowledge_search_service import KnowledgeSearchService
from services.graph.custom_message_writer import CustomSessionMessageWriter
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
        collection_id: int | None,
        rag_type_id: str | None,
        query: str,
        rag_search_config: RagSearchConfig | None,
        knowledge_search_service: KnowledgeSearchService,
        custom_session_message_writer: CustomSessionMessageWriter | None = None,
    ):
        super().__init__(
            session_id=session_id,
            node_name=node_name,
            stop_event=stop_event,
            input_map=input_map,
            output_variable_path=output_variable_path,
            custom_session_message_writer=custom_session_message_writer,
        )
        self.collection_id = collection_id
        self.rag_type_id = rag_type_id
        self.query_template = query
        self.rag_search_config = rag_search_config
        self.knowledge_search_service = knowledge_search_service

    async def execute(
        self, state: State, writer: StreamWriter, execution_order: int, input_: Any
    ) -> str:
        if self.collection_id is None or self.rag_type_id is None:
            raise ValueError(
                f"Knowledge node '{self.node_name}' is not configured: "
                "select a knowledge collection and RAG type."
            )

        if self.query_template:
            try:
                query = self.query_template.format(**input_)
            except (KeyError, IndexError, ValueError, TypeError):
                query = self.query_template
        elif isinstance(input_, dict):
            query = "\n".join(str(v) for v in input_.values())
        else:
            query = str(input_)

        if not query.strip():
            raise ValueError(
                f"Knowledge node '{self.node_name}' received an empty search query: "
                "set a query or map an input that resolves to non-empty text."
            )

        rag_search_config = (
            self.rag_search_config.model_dump() if self.rag_search_config else {}
        )
        try:
            chunks = await asyncio.to_thread(
                self.knowledge_search_service.search_knowledges,
                sender="node",
                knowledge_collection_id=self.collection_id,
                rag_type_id=self.rag_type_id,
                query=query,
                rag_search_config=rag_search_config,
                stop_event=self.stop_event,
            )
        except (RuntimeError, TimeoutError, ValueError) as e:
            raise KnowledgeSearchError(
                f"Knowledge node '{self.node_name}' search failed: {e}"
            ) from e

        if not chunks:
            return "No relevant results were found in the knowledge collection."

        return "\n\n".join(chunks)
