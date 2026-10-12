import asyncio
from unittest.mock import MagicMock

import pytest

from services.graph.events import StopEvent
from services.graph.nodes.knowledge_node import KnowledgeNode
from services.knowledge_search_service import KnowledgeSearchService
from src.shared.models import (
    FoundChunk,
    GraphRagBasicSearchParams,
    GraphRagSearchConfig,
    NaiveRagSearchConfig,
)


class FakeKnowledgeClient:
    """Stand-in for `clients.KnowledgeClient`: returns `search_result`, makes no HTTP calls."""

    search_result: list[FoundChunk] | str = [
        FoundChunk(order=0, similarity=0.9, text="chunk text", source="doc.txt")
    ]

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        pass

    def search(self, **kwargs):
        return self.search_result


def make_node(
    knowledge_search_service: KnowledgeSearchService,
    rag_type_id: str = "naive:2",
    rag_search_config=None,
) -> KnowledgeNode:
    return KnowledgeNode(
        session_id=1,
        node_name="knowledge_1",
        stop_event=StopEvent(),
        input_map={},
        output_variable_path=None,
        collection_id=5,
        rag_type_id=rag_type_id,
        query="hello world",
        rag_search_config=rag_search_config or NaiveRagSearchConfig(),
        knowledge_search_service=knowledge_search_service,
    )


def test_execute_emits_naive_extracted_chunks_message_shape(monkeypatch):
    monkeypatch.setattr(
        "services.knowledge_search_service.KnowledgeClient", FakeKnowledgeClient
    )
    service = KnowledgeSearchService(redis_service=MagicMock())
    writer = MagicMock()

    asyncio.run(
        make_node(service).execute(state={}, writer=writer, execution_order=3, input_={})
    )

    writer.assert_called_once()
    graph_message = writer.call_args[0][0]
    assert graph_message.session_id == 1
    assert graph_message.name == "knowledge_1"
    assert graph_message.execution_order == 3
    assert graph_message.message_data == {
        "message_type": "extracted_chunks",
        "rag_type": "naive",
        "collection_id": 5,
        "retrieved_chunks": 1,
        "knowledge_query": "hello world",
        "rag_search_config": {
            "rag_strategy": "naive",
            "search_limit": 3,
            "similarity_threshold": 0.2,
        },
        "chunks": [
            {"order": 0, "similarity": 0.9, "text": "chunk text", "source": "doc.txt"}
        ],
        "answer": None,
        "token_usage": {},
    }


@pytest.mark.parametrize("answer", ["graph answer", ""])
def test_execute_emits_graph_extracted_chunks_message_shape(monkeypatch, answer):
    monkeypatch.setattr(FakeKnowledgeClient, "search_result", answer)
    monkeypatch.setattr(
        "services.knowledge_search_service.KnowledgeClient", FakeKnowledgeClient
    )
    service = KnowledgeSearchService(redis_service=MagicMock())
    node = make_node(
        service,
        rag_type_id="graph:7",
        rag_search_config=GraphRagSearchConfig(
            search_params=GraphRagBasicSearchParams()
        ),
    )
    writer = MagicMock()

    asyncio.run(node.execute(state={}, writer=writer, execution_order=3, input_={}))

    message_data = writer.call_args[0][0].message_data
    rag_search_config = message_data.pop("rag_search_config")
    assert rag_search_config["rag_strategy"] == "graph"
    assert rag_search_config["method"] == "basic"
    assert message_data == {
        "message_type": "extracted_chunks",
        "rag_type": "graph",
        "collection_id": 5,
        "retrieved_chunks": 0,
        "knowledge_query": "hello world",
        "chunks": [],
        "answer": answer,
        "token_usage": {},
    }
