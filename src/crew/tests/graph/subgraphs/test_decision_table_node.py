"""Tests for DecisionTableNodeSubgraph error reporting.

The sandbox is replaced with a stub RunPythonCodeService, so the subgraph's own
condition/manipulation handling is exercised without a real venv.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from dotdict import DotDict
from langgraph.graph import StateGraph
from loguru import logger

from models.state import State
from services.graph.events import StopEvent

from src.crew.services.graph.subgraphs.decision_table_node import (
    DecisionTableNodeSubgraph,
)
from src.shared.models import ConditionGroupData, DecisionTableNodeData
from tests.graph.test_graph_builder import FakePythonCodeExecutorService


SANDBOX_STDERR = "Traceback: NameError at /opt/crew/secret_path.py, token sk-live-abcdef"


class StubRunPythonCodeService:
    """Return a fixed sandbox result for every run_code call."""

    def __init__(self, returncode: int, result_data: str = "null", stderr: str = ""):
        self._result = {
            "returncode": returncode,
            "result_data": result_data,
            "stderr": stderr,
            "execution_id": "test",
        }

    async def run_code(self, python_code_data, inputs, stop_event=None, storage_credentials=None):
        return dict(self._result)


def make_state(variables: dict | None = None) -> State:
    return {
        "state_history": [],
        "variables": DotDict(variables or {}),
        "system_variables": {"nodes": {}, "execution_order": 0},
        "execution_counts": {},
    }


def build_subgraph(node_data: DecisionTableNodeData, run_code_service):
    redis_service = MagicMock()
    redis_service.aadd_graph_message = AsyncMock()
    subgraph = DecisionTableNodeSubgraph(
        session_id=1,
        decision_table_node_data=node_data,
        graph_builder=StateGraph(State),
        stop_event=StopEvent(),
        run_code_execution_service=run_code_service,
        redis_service=redis_service,
    ).build()
    return subgraph, redis_service


def published_messages(redis_service: MagicMock) -> list[dict]:
    return [
        json.loads(added.args[1])["message_data"]
        for added in redis_service.aadd_graph_message.await_args_list
    ]


def complex_group(group_name: str, expression: str, next_node: str) -> ConditionGroupData:
    return ConditionGroupData(
        group_name=group_name,
        group_type="complex",
        expression=expression,
        next_node=next_node,
    )


@pytest.mark.asyncio
async def test_matching_condition_group_routes_to_its_next_node():
    node_data = DecisionTableNodeData(
        node_name="dt_node",
        conditional_group_list=[complex_group("hit", "True", "node_A")],
        default_next_node="fallback",
    )
    subgraph, _ = build_subgraph(node_data, StubRunPythonCodeService(0, result_data="true"))

    result = await subgraph.ainvoke(make_state())

    assert result["system_variables"]["nodes"]["dt_node"]["result_node"] == "node_A"


def error_details(redis_service: MagicMock) -> list[str]:
    return [
        message["error"]["detail"]
        for message in published_messages(redis_service)
        if message["message_type"] == "error"
    ]


@pytest.fixture
def captured_logs():
    records: list[str] = []
    sink_id = logger.add(records.append, level="WARNING")
    yield records
    logger.remove(sink_id)


@pytest.mark.asyncio
async def test_failing_condition_group_names_the_condition_before_the_stderr():
    """The sandbox's stderr is already the text meant for the user (the user's own
    error or the sandbox's fixed platform text); the node only names the condition."""
    node_data = DecisionTableNodeData(
        node_name="dt_node",
        conditional_group_list=[complex_group("High score", "undefined_name", "node_A")],
        next_error_node="error_node",
    )
    subgraph, redis_service = build_subgraph(
        node_data, StubRunPythonCodeService(1, stderr=SANDBOX_STDERR)
    )

    result = await subgraph.ainvoke(make_state())

    assert result["system_variables"]["nodes"]["dt_node"]["result_node"] == "error_node"
    assert [
        message["error"]
        for message in published_messages(redis_service)
        if message["message_type"] == "error"
    ] == [
        {
            "code": "decision_table_failed",
            "detail": f'Condition "High score": {SANDBOX_STDERR}',
            "attr": None,
            "context": None,
        }
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("group", "expected"),
    [
        pytest.param(
            complex_group("High score", "scroe > 3", "node_A"),
            "Condition \"High score\": name 'scroe' is not defined",
            id="user-error-in-expression-kept-as-raised",
        ),
        pytest.param(
            complex_group("High score", "'yes'", "node_A"),
            "Condition \"High score\" didn't give true or false.",
            id="expression-not-boolean",
        ),
        pytest.param(
            ConditionGroupData(
                group_name="High score",
                group_type="complex",
                expression="True",
                manipulation="variables['total'] = undefined_total",
                next_node="node_A",
            ),
            "Condition \"High score\": name 'undefined_total' is not defined",
            id="user-error-in-manipulation-kept-as-raised",
        ),
    ],
)
async def test_condition_failure_streams_its_fact(group, expected):
    node_data = DecisionTableNodeData(
        node_name="dt_node", conditional_group_list=[group], next_error_node="error_node"
    )
    subgraph, redis_service = build_subgraph(node_data, FakePythonCodeExecutorService())

    result = await subgraph.ainvoke(make_state({"score": 5}))

    assert result["system_variables"]["nodes"]["dt_node"]["result_node"] == "error_node"
    assert error_details(redis_service) == [expected]


@pytest.mark.asyncio
async def test_unreadable_code_result_streams_the_server_error_fact_and_logs_the_data(captured_logs):
    node_data = DecisionTableNodeData(
        node_name="dt_node",
        conditional_group_list=[complex_group("High score", "True", "node_A")],
        next_error_node="error_node",
    )
    subgraph, redis_service = build_subgraph(
        node_data, StubRunPythonCodeService(0, result_data="<html>proxy at internal-host</html>")
    )

    await subgraph.ainvoke(make_state())

    assert error_details(redis_service) == [
        "Condition \"High score\": The code couldn't run because of a server error."
    ]
    assert any("internal-host" in record for record in captured_logs)


SANDBOX_LOST_RESULT = {
    "returncode": 1,
    "result_data": None,
    "stderr": "",
    "error": {
        "code": "worker_lost",
        "detail": "Sandbox worker was lost; the job may not have finished.",
    },
    "execution_id": "test",
}
TRUE_RESULT = {"returncode": 0, "result_data": "true", "stderr": "", "error": None, "execution_id": "test"}


class SequenceRunPythonCodeService:
    """Return the given sandbox results one run_code call after another."""

    def __init__(self, *results: dict):
        self._results = list(results)

    async def run_code(self, python_code_data, inputs, stop_event=None, storage_credentials=None):
        return dict(self._results.pop(0))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("group", "results"),
    [
        pytest.param(
            complex_group("High score", "True", "node_A"),
            [SANDBOX_LOST_RESULT],
            id="expression",
        ),
        pytest.param(
            ConditionGroupData(
                group_name="High score",
                group_type="complex",
                expression="True",
                manipulation="variables['total'] = 1",
                next_node="node_A",
            ),
            [TRUE_RESULT, SANDBOX_LOST_RESULT],
            id="manipulation",
        ),
    ],
)
async def test_a_sandbox_failure_streams_its_error_detail_after_the_condition(group, results):
    node_data = DecisionTableNodeData(
        node_name="dt_node", conditional_group_list=[group], next_error_node="error_node"
    )
    subgraph, redis_service = build_subgraph(node_data, SequenceRunPythonCodeService(*results))

    result = await subgraph.ainvoke(make_state())

    assert result["system_variables"]["nodes"]["dt_node"]["result_node"] == "error_node"
    assert error_details(redis_service) == [
        'Condition "High score": Sandbox worker was lost; the job may not have finished.'
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("stderr", "error", "expected_details"),
    [
        pytest.param(
            "child wrote this",
            {"code": "unsafe_control_file", "detail": "The code couldn't run because of a server error."},
            'Condition "High score": child wrote this\nThe code couldn\'t run because of a server error.',
            id="code-wrote-then-sandbox-failed",
        ),
        pytest.param(
            "",
            {"code": "worker_lost", "detail": "Sandbox worker was lost; the job may not have finished.", "attr": None},
            'Condition "High score": Sandbox worker was lost; the job may not have finished.',
            id="error-with-an-extra-field",
        ),
    ],
)
async def test_a_condition_shows_the_codes_stderr_before_the_sandbox_error(
    stderr, error, expected_details
):
    failed = {**SANDBOX_LOST_RESULT, "stderr": stderr, "error": error}
    node_data = DecisionTableNodeData(
        node_name="dt_node",
        conditional_group_list=[complex_group("High score", "True", "node_A")],
        next_error_node="error_node",
    )
    subgraph, redis_service = build_subgraph(node_data, SequenceRunPythonCodeService(failed))

    await subgraph.ainvoke(make_state())

    assert error_details(redis_service) == [expected_details]
