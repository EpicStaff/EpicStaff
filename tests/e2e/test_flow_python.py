"""Flow A end to end: Start -> Python (`a + b`) -> End, deterministic and without an LLM.

One run per module, shared by the tests below; each test asserts one stage of it.
"""

import pytest

from helpers.api import ApiClient
from helpers.bootstrap import unique_suffix
from helpers.flows import (
    CreatedFlow,
    FlowRun,
    assert_session_ended,
    create_python_flow,
    run_flow_and_wait,
    runtime_node_name,
    wait_for_graph_end,
)
from helpers.payloads import PYTHON_NODE_NAME, PYTHON_SUM_CODE
from helpers.polling import session_diagnostics

RUN_VARIABLES = {"a": 2, "b": 3}
EXPECTED_RESULT = {"sum": 5}
# The warm-up already paid the sandbox cold start; a warm run takes seconds.
RUN_TIMEOUT_SECONDS = 120
# Django writes buffered messages to the database every ~3 s.
MESSAGES_TIMEOUT_SECONDS = 30


@pytest.fixture(scope="module")
def python_flow(user_client: ApiClient) -> CreatedFlow:
    return create_python_flow(user_client, f"e2e-python-{unique_suffix()}")


@pytest.fixture(scope="module")
def python_flow_run(user_client: ApiClient, python_flow: CreatedFlow, timings) -> FlowRun:
    run = run_flow_and_wait(user_client, python_flow.graph_id, RUN_VARIABLES, RUN_TIMEOUT_SECONDS)
    timings.record("flow_python_run_seconds", run.run_seconds)
    return run


@pytest.fixture(scope="module")
def python_flow_session(user_client: ApiClient, python_flow_run: FlowRun) -> dict:
    return user_client.get(f"/api/sessions/{python_flow_run.session_id}/").json()


@pytest.fixture(scope="module")
def python_flow_messages(
    user_client: ApiClient, python_flow_run: FlowRun, python_flow_session: dict
) -> list[dict]:
    # A run that did not end never writes graph_end: fail now, not after the message budget.
    assert_session_ended(user_client, python_flow_run.session_id, python_flow_session["status"])
    return wait_for_graph_end(user_client, python_flow_run.session_id, MESSAGES_TIMEOUT_SECONDS)


def python_node_message_name(flow: CreatedFlow) -> str:
    [python_node] = flow.saved["python_node_list"]
    return runtime_node_name(python_node)


def messages_of_type(messages: list[dict], message_type: str, name: str | None = None) -> list[dict]:
    return [
        message
        for message in messages
        if message["message_data"].get("message_type") == message_type
        and (name is None or message["name"] == name)
    ]


def test_graph_is_created_and_saved(python_flow: CreatedFlow) -> None:
    assert python_flow.created["save_version"] == 1
    assert python_flow.created["name"].startswith("e2e-python-")

    saved = python_flow.saved
    assert saved["id"] == python_flow.graph_id
    assert saved["save_version"] == 2
    [start_node] = saved["start_node_list"]
    [python_node] = saved["python_node_list"]
    [end_node] = saved["end_node_list"]
    assert python_node["node_name"] == PYTHON_NODE_NAME
    assert python_node["python_code"]["code"] == PYTHON_SUM_CODE
    assert python_node["output_variable_path"] == "variables.result"
    assert end_node["output_map"] == {"result": "variables.result"}
    edges = {(edge["start_node_id"], edge["end_node_id"]) for edge in saved["edge_list"]}
    assert edges == {(start_node["id"], python_node["id"]), (python_node["id"], end_node["id"])}


def test_run_session_returns_a_session_id(python_flow_run: FlowRun) -> None:
    assert isinstance(python_flow_run.run_session_body["session_id"], int)


def test_session_ends_with_the_sum(
    user_client: ApiClient, python_flow_run: FlowRun, python_flow_session: dict
) -> None:
    assert_session_ended(user_client, python_flow_run.session_id, python_flow_session["status"])
    assert python_flow_session["status_data"]["variables"]["result"] == EXPECTED_RESULT, (
        session_diagnostics(user_client, python_flow_run.session_id)
    )
    assert python_flow_session["finished_at"] is not None
    # `variables` keeps the run input; the final state lives in `status_data.variables`.
    assert python_flow_session["variables"] == RUN_VARIABLES


def test_session_messages_trace_the_run(
    python_flow: CreatedFlow, python_flow_messages: list[dict]
) -> None:
    [graph_end] = messages_of_type(python_flow_messages, "graph_end")
    assert graph_end["message_data"]["end_node_result"] == {"result": EXPECTED_RESULT}

    node_name = python_node_message_name(python_flow)
    [python_message] = messages_of_type(python_flow_messages, "python", node_name)
    execution = python_message["message_data"]["python_code_execution_data"]
    assert execution["returncode"] == 0, execution

    [start] = messages_of_type(python_flow_messages, "start", node_name)
    assert start["message_data"]["input"] == RUN_VARIABLES
    [finish] = messages_of_type(python_flow_messages, "finish", node_name)
    assert finish["message_data"]["output"] == EXPECTED_RESULT
