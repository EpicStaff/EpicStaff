"""Flow B end to end: Start -> Knowledge (naive RAG) -> Task (agent with the RAG tool) -> End.

The agent runs on mock-llm: it calls the `search_*` knowledge tool with the question, then
answers `ANSWER: <tool result>`, so the token reaches the answer only through the RAG tool.
"""

import functools

import pytest

from fixtures.knowledge import IndexedRag
from helpers.api import ApiClient
from helpers.bootstrap import unique_suffix
from helpers.flows import (
    CreatedFlow,
    FlowRun,
    assert_session_ended,
    create_flow,
    run_flow_and_wait,
    runtime_name_of,
    wait_for_graph_end,
)
from helpers.mock_llm import CHAT_COMPLETIONS_PATH, MockLlmClient
from helpers.payloads import AGENT_RAG_QUESTION, agent_rag_flow_save_payload
from helpers.polling import session_diagnostics
from helpers.timings import Timings

# No python node, so no sandbox venv build: the run is the agent loop plus two searches.
RUN_TIMEOUT_SECONDS = 180
MESSAGES_TIMEOUT_SECONDS = 30


@pytest.fixture(scope="module")
def agent_rag_flow(
    user_client: ApiClient,
    rag_collection: dict,
    naive_rag: dict,
    indexed_rag: IndexedRag,
    knowledge_surface: dict,
    e2e_agent: dict,
) -> CreatedFlow:
    build_payload = functools.partial(
        agent_rag_flow_save_payload,
        collection_id=rag_collection["collection_id"],
        naive_rag_id=naive_rag["naive_rag"]["naive_rag_id"],
        agent_definition_id=e2e_agent["id"],
        surface_id=knowledge_surface["id"],
    )
    return create_flow(user_client, f"e2e-agent-rag-{unique_suffix()}", build_payload)


@pytest.fixture(scope="module")
def agent_rag_run(user_client: ApiClient, agent_rag_flow: CreatedFlow, timings: Timings) -> FlowRun:
    # Empty input: the question comes from the Start node's variables.
    run = run_flow_and_wait(user_client, agent_rag_flow.graph_id, {}, RUN_TIMEOUT_SECONDS)
    timings.record("flow_agent_rag_run_seconds", run.run_seconds)
    return run


@pytest.fixture(scope="module")
def agent_rag_session(user_client: ApiClient, agent_rag_run: FlowRun) -> dict:
    session = user_client.get(f"/api/sessions/{agent_rag_run.session_id}/").json()
    assert_session_ended(user_client, agent_rag_run.session_id, session["status"])
    return session


@pytest.fixture(scope="module")
def agent_rag_messages(
    user_client: ApiClient, agent_rag_run: FlowRun, agent_rag_session: dict
) -> list[dict]:
    return wait_for_graph_end(user_client, agent_rag_run.session_id, MESSAGES_TIMEOUT_SECONDS)


def message_text(content: object) -> str:
    """OpenAI message content: a string or a list of `{"type": "text", "text": ...}` parts."""
    if isinstance(content, list):
        return "".join(part.get("text", "") for part in content if isinstance(part, dict))
    return str(content or "")


def test_flow_is_saved_with_both_nodes(
    agent_rag_flow: CreatedFlow, naive_rag: dict, knowledge_surface: dict, e2e_agent: dict
) -> None:
    [knowledge_node] = agent_rag_flow.saved["knowledge_node_list"]
    assert knowledge_node["rag_type"] == "naive"
    assert knowledge_node["rag_id"] == naive_rag["naive_rag"]["naive_rag_id"]
    assert knowledge_node["search_configs"]["naive"]["search_limit"] == 3
    [task_node] = agent_rag_flow.saved["task_node_list"]
    assert task_node["agent_definition"] == e2e_agent["id"]
    assert task_node["surface_list"] == [knowledge_surface["id"]]


def test_session_ends(agent_rag_session: dict) -> None:
    assert agent_rag_session["status"] == "end"
    assert agent_rag_session["finished_at"] is not None


def test_knowledge_node_finds_the_token(
    user_client: ApiClient, agent_rag_run: FlowRun, agent_rag_session: dict, knowledge_token: str
) -> None:
    kb_hits = agent_rag_session["status_data"]["variables"]["kb_hits"]
    assert knowledge_token in kb_hits, session_diagnostics(user_client, agent_rag_run.session_id)


def test_agent_answers_from_the_rag_tool(
    user_client: ApiClient, agent_rag_run: FlowRun, agent_rag_session: dict, knowledge_token: str
) -> None:
    answer = agent_rag_session["status_data"]["variables"]["answer"]
    assert knowledge_token in answer, session_diagnostics(user_client, agent_rag_run.session_id)


def extracted_chunks_of(messages: list[dict], node_name: str) -> list[dict]:
    return [
        message["message_data"]
        for message in messages
        if message["name"] == node_name
        and message["message_data"].get("message_type") == "extracted_chunks"
    ]


def test_knowledge_node_records_its_retrieval(
    agent_rag_flow: CreatedFlow, agent_rag_messages: list[dict], knowledge_token: str
) -> None:
    knowledge_name = runtime_name_of(agent_rag_flow, "knowledge_node_list")
    [retrieval] = extracted_chunks_of(agent_rag_messages, knowledge_name)
    assert retrieval["knowledge_query"] == AGENT_RAG_QUESTION
    assert any(knowledge_token in chunk["text"] for chunk in retrieval["chunks"]), retrieval


def test_agent_tool_call_is_recorded_as_a_knowledge_search(
    agent_rag_flow: CreatedFlow, agent_rag_messages: list[dict], e2e_agent: dict, knowledge_token: str
) -> None:
    """The agent's RAG tool call is recorded as `extracted_chunks`, not `task_node_stream`.

    The agent service suppresses live `tool_call` / `tool_result` events for knowledge tools
    and sends the richer `agent.knowledge_search` envelope instead
    (agent/app/emitters/redis_tool_events.py), which crew writes as `extracted_chunks`.
    """
    task_name = runtime_name_of(agent_rag_flow, "task_node_list")
    [search] = extracted_chunks_of(agent_rag_messages, task_name)
    assert search["agent_id"] == e2e_agent["id"]
    assert search["rag_type"] == "naive"
    assert any(knowledge_token in chunk["text"] for chunk in search["chunks"]), search


def test_mock_llm_received_the_tool_result(
    agent_rag_session: dict, mock_llm: MockLlmClient, knowledge_token: str
) -> None:
    # Filtered by this run's token: a marker alone cannot separate overlapping runs.
    tool_messages = [
        message_text(message.get("content"))
        for call in mock_llm.calls()
        if call["path"] == CHAT_COMPLETIONS_PATH
        for message in call["body"].get("messages", [])
        if message.get("role") == "tool"
    ]
    assert any(knowledge_token in text for text in tool_messages), (
        f"no chat request carried a tool message with the token ({len(tool_messages)} tool messages)"
    )
