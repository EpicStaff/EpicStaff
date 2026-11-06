import asyncio
import re
from unittest.mock import MagicMock

import pytest
from dotdict import DotDict
from loguru import logger

from clients.errors import ClientBadGatewayError, ClientNotAvailableError, ClientTimeoutError
from services.graph.events import StopEvent
from services.graph.exceptions import NodeExecutionError
from services.graph.nodes.knowledge_node import KnowledgeNode
from services.knowledge_search_service import KnowledgeSearchService
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
        FoundChunk(order=0, similarity=0.9, text="chunk text", source="doc.txt")
    ]

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        pass

    search_usage: SearchUsage = SearchUsage()

    def search_with_usage(self, **kwargs):
        return SearchOutcome(result=self.search_result, usage=self.search_usage)


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


def test_execute_forwards_extra_headers_to_the_search(monkeypatch):
    received = {}

    class CapturingKnowledgeClient(FakeKnowledgeClient):
        def search_with_usage(self, **kwargs):
            received.update(kwargs)
            return SearchOutcome(result=[])

    monkeypatch.setattr(
        "services.knowledge_search_service.KnowledgeClient", CapturingKnowledgeClient
    )
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
        knowledge_search_service=KnowledgeSearchService(redis_service=MagicMock()),
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
    monkeypatch.setattr(
        "services.knowledge_search_service.KnowledgeClient", FakeKnowledgeClient
    )
    writer = MagicMock()

    asyncio.run(
        make_node(KnowledgeSearchService(redis_service=MagicMock())).execute(
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
    monkeypatch.setattr(
        "services.knowledge_search_service.KnowledgeClient", FakeKnowledgeClient
    )
    writer = MagicMock()

    asyncio.run(
        make_node(KnowledgeSearchService(redis_service=MagicMock())).execute(
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


# How Django names a node it sends to crew: "<name> #<number> #<node id>".
SEARCH_DOCS_RUNTIME_NAME = "Search docs #1 #4512"
RAW_KNOWLEDGE_ERROR = "<html>500 at http://knowledge_new:8100/rags/naive/2/search/ sk-embed-secret</html>"


@pytest.fixture
def captured_error_logs():
    records: list[str] = []
    sink_id = logger.add(records.append, level="ERROR")
    yield records
    logger.remove(sink_id)


def make_search_docs_node(
    service: KnowledgeSearchService,
    query: str = "hello world",
    input_map: dict | None = None,
    rag_type_id: str = "naive:2",
) -> KnowledgeNode:
    return KnowledgeNode(
        session_id=1,
        node_name=SEARCH_DOCS_RUNTIME_NAME,
        stop_event=StopEvent(),
        input_map=input_map or {},
        output_variable_path=None,
        collection_id=5,
        rag_type_id=rag_type_id,
        query=query,
        rag_search_config=NaiveRagSearchConfig(),
        knowledge_search_service=service,
    )


async def run_failing(node: KnowledgeNode, variables: dict) -> tuple[NodeExecutionError, list[str]]:
    """Run `node` the way the graph does; return the raised error and the streamed error texts."""
    messages = []
    state = {"variables": DotDict(variables), "state_history": [], "system_variables": {}}
    with pytest.raises(NodeExecutionError) as raised:
        await node.run(state, writer=messages.append)
    details = [
        message.message_data.details
        for message in messages
        if getattr(message.message_data, "message_type", None) == "error"
    ]
    return raised.value, details


class CountingKnowledgeClient(FakeKnowledgeClient):
    searches = 0

    def search_with_usage(self, **kwargs):
        type(self).searches += 1
        return super().search_with_usage(**kwargs)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("query", "input_map", "variables"),
    [
        ("", {}, {}),
        ("{topic}", {"topic": "variables.topic"}, {"topic": "   "}),
    ],
    ids=["no-query", "mapped-input-is-blank"],
)
async def test_empty_query_tells_the_user_how_to_fix_it_without_searching(
    monkeypatch, query, input_map, variables
):
    monkeypatch.setattr(CountingKnowledgeClient, "searches", 0)
    monkeypatch.setattr(
        "services.knowledge_search_service.KnowledgeClient", CountingKnowledgeClient
    )
    node = make_search_docs_node(
        KnowledgeSearchService(redis_service=MagicMock()), query=query, input_map=input_map
    )

    error, details = await run_failing(node, variables)

    expected = (
        'Knowledge Retriever node "Search docs #1" got an empty query. '
        "Set a query, or map an input that has text."
    )
    assert details == [expected]
    assert error.public_message == expected
    assert error.reference is None
    assert CountingKnowledgeClient.searches == 0


def _client_failing_with(error: Exception):
    class FailingKnowledgeClient(FakeKnowledgeClient):
        def search_with_usage(self, **kwargs):
            raise error

    return FailingKnowledgeClient


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("client_error", "rag_type_id", "logged_error"),
    [
        (ClientTimeoutError("slow"), "naive:2", "Knowledge search timeout for naive:2"),
        (ClientBadGatewayError(RAW_KNOWLEDGE_ERROR), "naive:2", RAW_KNOWLEDGE_ERROR),
        (ClientNotAvailableError(RAW_KNOWLEDGE_ERROR), "naive:2", RAW_KNOWLEDGE_ERROR),
        (None, "naive:sk-embed-secret", "Invalid rag_type_id format: 'naive:sk-embed-secret'"),
    ],
    ids=["timeout", "service-error", "unreachable", "bad-collection-reference"],
)
async def test_failed_search_shows_a_reference_and_logs_the_raw_error_under_it(
    monkeypatch, captured_error_logs, client_error, rag_type_id, logged_error
):
    monkeypatch.setattr(
        "services.knowledge_search_service.KnowledgeClient", _client_failing_with(client_error)
    )
    node = make_search_docs_node(
        KnowledgeSearchService(redis_service=MagicMock()), rag_type_id=rag_type_id
    )

    error, details = await run_failing(node, {})

    reference = re.search(r"reference: ([0-9a-f]{12})", details[0]).group(1)
    expected = (
        "Knowledge Retriever node \"Search docs #1\" couldn't search its collection. "
        f"Try again or contact your administrator (reference: {reference})."
    )
    assert details == [expected]
    assert error.public_message == expected
    assert error.reference == reference
    reference_logs = [record for record in captured_error_logs if reference in record]
    assert len(reference_logs) == 1
    assert logged_error in reference_logs[0]
