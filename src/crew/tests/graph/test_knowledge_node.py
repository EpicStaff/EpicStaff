import asyncio
from unittest.mock import MagicMock

import pytest
from dotdict import DotDict
from loguru import logger

import httpx
from foundation.transport.http import (
    ClientBadGatewayError,
    ClientConnectionError,
    ClientTimeoutError,
    ClientValidationError,
)
from services.graph.events import StopEvent
from services.graph.exceptions import KnowledgeSearchError
from services.graph.nodes.knowledge_node import KnowledgeNode
from services.knowledge_search_service import KnowledgeSearchService
from src.shared.flow_templates import RefusedPlaceholderError
from src.shared.models import (
    FoundChunk,
    GraphRagBasicSearchParams,
    GraphRagSearchConfig,
    NaiveRagSearchConfig,
    SearchOutcome,
    SearchUsage,
)


class FakeKnowledgeClient:
    """Stand-in for `clients.KnowledgeClient`: returns `search_result`, makes no HTTP calls."""

    search_result: list[FoundChunk] | str = [
        FoundChunk(
            order=0, similarity=0.9, text="chunk text", source="doc.txt", document_id=11
        )
    ]

    search_usage: SearchUsage = SearchUsage()

    async def search_with_usage(self, **kwargs):
        return SearchOutcome(result=self.search_result, usage=self.search_usage)


def make_service(knowledge_client=None) -> KnowledgeSearchService:
    return KnowledgeSearchService(
        redis_service=MagicMock(), knowledge_client=knowledge_client or FakeKnowledgeClient()
    )


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


def test_execute_emits_naive_extracted_chunks_message_shape():
    service = make_service()
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
        "rag_id": 2,
        "retrieved_chunks": 1,
        "knowledge_query": "hello world",
        "rag_search_config": {
            "rag_strategy": "naive",
            "search_limit": 3,
            "similarity_threshold": 0.2,
        },
        "chunks": [
            {
                "order": 0,
                "similarity": 0.9,
                "text": "chunk text",
                "source": "doc.txt",
                "document_id": 11,
            }
        ],
        "answer": None,
        "token_usage": {},
    }


@pytest.mark.parametrize("answer", ["graph answer", ""])
def test_execute_emits_graph_extracted_chunks_message_shape(monkeypatch, answer):
    monkeypatch.setattr(FakeKnowledgeClient, "search_result", answer)
    service = make_service()
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
        "rag_id": 7,
        "retrieved_chunks": 0,
        "knowledge_query": "hello world",
        "chunks": [],
        "answer": answer,
        "token_usage": {},
    }


def test_execute_forwards_extra_headers_to_the_search():
    received = {}

    class CapturingKnowledgeClient(FakeKnowledgeClient):
        async def search_with_usage(self, **kwargs):
            received.update(kwargs)
            return SearchOutcome(result=[])

    node = KnowledgeNode(
        session_id=1,
        node_name="knowledge_1",
        stop_event=StopEvent(),
        input_map={},
        output_variable_path=None,
        collection_id=5,
        rag_type_id="graph:7",
        query="hello world",
        rag_search_config=GraphRagSearchConfig(search_params=GraphRagBasicSearchParams()),
        knowledge_search_service=make_service(CapturingKnowledgeClient()),
        embedder_extra_headers={"X-Emb": "emb-resolved"},
        llm_extra_headers={"X-Llm": "llm-resolved"},
    )

    asyncio.run(node.execute(state={}, writer=MagicMock(), execution_order=1, input_={}))

    assert received["embedding_extra_headers"] == {"X-Emb": "emb-resolved"}
    assert received["llm_extra_headers"] == {"X-Llm": "llm-resolved"}


def test_execute_adds_search_embedding_usage_to_the_message_token_usage(monkeypatch):
    monkeypatch.setattr(
        FakeKnowledgeClient,
        "search_usage",
        SearchUsage(embedding_tokens=12, embedding_cost_usd=0.0002),
    )
    writer = MagicMock()

    asyncio.run(
        make_node(make_service()).execute(
            state={}, writer=writer, execution_order=3, input_={}
        )
    )

    message_data = writer.call_args[0][0].message_data
    assert message_data["token_usage"] == {
        "prompt_tokens": 12,
        "completion_tokens": 0,
        "total_tokens": 12,
        "total_cost_usd": 0.0002,
    }


def test_execute_adds_graph_search_llm_usage_to_the_message_token_usage(monkeypatch):
    monkeypatch.setattr(
        FakeKnowledgeClient,
        "search_usage",
        SearchUsage(
            embedding_tokens=10,
            embedding_cost_usd=0.0001,
            llm_input_tokens=100,
            llm_output_tokens=20,
            llm_cost_usd=0.003,
        ),
    )
    writer = MagicMock()

    asyncio.run(
        make_node(make_service()).execute(
            state={}, writer=writer, execution_order=3, input_={}
        )
    )

    token_usage = writer.call_args[0][0].message_data["token_usage"]
    assert token_usage["prompt_tokens"] == 110
    assert token_usage["completion_tokens"] == 20
    assert token_usage["total_tokens"] == 130
    assert token_usage["total_cost_usd"] == 0.0031


def test_search_usage_with_unknown_llm_cost_counts_it_as_zero():
    usage = SearchUsage(llm_input_tokens=5, llm_output_tokens=3, llm_cost_usd=None)

    assert usage.to_token_usage() == {
        "prompt_tokens": 5,
        "completion_tokens": 3,
        "total_tokens": 8,
        "total_cost_usd": 0.0,
    }


def test_empty_search_usage_has_no_token_usage():
    assert SearchUsage().to_token_usage() == {}


def search_query(query_template: str, input_: dict) -> str:
    """Run the node with `query_template` and return the query sent to the knowledge service."""
    received = {}

    class CapturingKnowledgeClient(FakeKnowledgeClient):
        async def search_with_usage(self, **kwargs):
            received.update(kwargs)
            return SearchOutcome(result=[])

    node = make_node(make_service(CapturingKnowledgeClient()))
    node.query_template = query_template

    asyncio.run(node.execute(state={}, writer=MagicMock(), execution_order=1, input_=input_))

    return received["query"]


@pytest.mark.parametrize(
    ("query_template", "expected_query"),
    [
        ("Docs about {topic}", "Docs about cats"),
        ("Docs about {topic} and {missing}", "Docs about cats and {missing}"),
        ("Docs {{literal}} about {topic}", "Docs {literal} about cats"),
        ('Docs like {"a": 1} about {topic}', 'Docs like {"a": 1} about {topic}'),
        ("Docs about {topic.upper}", "Docs about {topic.upper}"),
        ("Docs about {q[text]}", "Docs about dogs"),
    ],
    ids=[
        "plain",
        "missing-left-as-written",
        "escaped-braces",
        "json-example-verbatim",
        "attribute-of-text-left-as-written",
        "key-path",
    ],
)
def test_query_is_rendered_from_the_input(query_template, expected_query):
    query = search_query(query_template, {"topic": "cats", "q": {"text": "dogs"}})

    assert query == expected_query


class RecordingKnowledgeSearchService:
    def __init__(self):
        self.searches = []

    async def search_knowledges(self, **kwargs):
        self.searches.append(kwargs)
        return []


def test_refused_query_placeholder_fails_before_any_search():
    service = RecordingKnowledgeSearchService()
    node = make_node(service)
    node.query_template = "Docs about {q._x}"

    with pytest.raises(RefusedPlaceholderError):
        asyncio.run(
            node.execute(state={}, writer=MagicMock(), execution_order=1, input_={"q": {"_x": "x"}})
        )

    assert service.searches == []


def run_node(node: KnowledgeNode) -> list:
    """Run the node through BaseNode.run and return the streamed message data."""
    state = {"variables": DotDict({}), "state_history": [], "system_variables": {}}
    messages = []
    with pytest.raises(KnowledgeSearchError):
        asyncio.run(node.run(state, writer=messages.append))
    return [
        message.message_data.error["detail"]
        for message in messages
        if getattr(message.message_data, "message_type", None) == "error"
    ]


def knowledge_response(status_code: int) -> httpx.Response:
    return httpx.Response(status_code, request=httpx.Request("POST", "http://knowledge-internal:8001/search"))


@pytest.fixture
def captured_logs():
    records: list[str] = []
    sink_id = logger.add(records.append, level="WARNING")
    yield records
    logger.remove(sink_id)


def test_empty_query_streams_the_fact_without_searching():
    service = RecordingKnowledgeSearchService()
    node = make_node(service)
    node.node_name = "Search docs #1 #12"
    node.query_template = "   "

    assert run_node(node) == ['Knowledge Retriever node "Search docs #1" got an empty query.']
    assert service.searches == []


@pytest.mark.parametrize(
    ("service_error", "logged_text"),
    [
        (
            ClientBadGatewayError(
                "<html>502 at http://knowledge-internal:8001 key=sk-abc123</html>",
                response=knowledge_response(502),
            ),
            "knowledge-internal:8001",
        ),
        (
            ClientValidationError(
                '{"detail": "rag 2 at http://knowledge-internal:8001 not indexed"}',
                response=knowledge_response(400),
            ),
            "knowledge-internal:8001",
        ),
        (
            ClientConnectionError("Knowledge service is unreachable at knowledge-internal:8001."),
            "knowledge-internal:8001",
        ),
        # KnowledgeSearchService turns a client timeout into its own TimeoutError text.
        (ClientTimeoutError("knowledge-internal:8001 timed out"), "Knowledge search timeout"),
    ],
    ids=["5xx", "4xx", "unreachable", "timeout"],
)
def test_failed_search_streams_the_fact_and_logs_the_service_text(
    captured_logs, service_error, logged_text
):
    class FailingKnowledgeClient(FakeKnowledgeClient):
        async def search_with_usage(self, **kwargs):
            raise service_error

    node = make_node(make_service(FailingKnowledgeClient()))
    node.node_name = "Search docs #1 #12"

    assert run_node(node) == [
        'Knowledge Retriever node "Search docs #1" couldn\'t search its collection.'
    ]
    assert any(logged_text in record for record in captured_logs)
