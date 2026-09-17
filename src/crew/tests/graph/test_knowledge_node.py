import asyncio
from unittest.mock import MagicMock

from services.graph.events import StopEvent
from services.graph.nodes.knowledge_node import KnowledgeNode
from services.knowledge_search_service import KnowledgeSearchService
from src.shared.models import FoundChunk, NaiveRagSearchConfig


class FakeKnowledgeClient:
    """Stand-in for `clients.KnowledgeClient`: returns fixed chunks, makes no HTTP calls."""

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        pass

    def search(self, **kwargs):
        return [
            FoundChunk(order=0, similarity=0.9, text="chunk text", source="doc.txt")
        ]


def make_node(knowledge_search_service: KnowledgeSearchService) -> KnowledgeNode:
    return KnowledgeNode(
        session_id=1,
        node_name="knowledge_1",
        stop_event=StopEvent(),
        input_map={},
        output_variable_path=None,
        collection_id=5,
        rag_type_id="naive:2",
        query="hello world",
        rag_search_config=NaiveRagSearchConfig(),
        knowledge_search_service=knowledge_search_service,
    )


def test_execute_writes_extracted_chunks_message_to_stream(monkeypatch):
    monkeypatch.setattr(
        "services.knowledge_search_service.KnowledgeClient", FakeKnowledgeClient
    )
    service = KnowledgeSearchService(redis_service=MagicMock())
    node = make_node(service)
    writer = MagicMock()

    asyncio.run(node.execute(state={}, writer=writer, execution_order=3, input_={}))

    writer.assert_called_once()
    graph_message = writer.call_args[0][0]
    message_data = graph_message.message_data

    assert graph_message.session_id == 1
    assert graph_message.name == "knowledge_1"
    assert graph_message.execution_order == 3
    assert message_data["message_type"] == "extracted_chunks"
    assert "crew_id" not in message_data
    assert "agent_id" not in message_data
    assert message_data["collection_id"] == 5
    assert message_data["knowledge_query"] == "hello world"
    assert message_data["chunks"] == [
        {"order": 0, "similarity": 0.9, "text": "chunk text", "source": "doc.txt"}
    ]
