"""Tests for DecisionTableNodeSubgraph routing and the errors it shows the user.

Conditions and manipulations run through the sandbox's own code wrapper
(`SandboxWrapperRunCodeService`), so the messages are checked against what the sandbox
really reports for the code the node generates. Failures of the sandbox service itself
come from a stub returning the results `RunPythonCodeService` makes up for them.
"""

from __future__ import annotations

import json
import re
from unittest.mock import AsyncMock, MagicMock

import pytest
from dotdict import DotDict
from langgraph.graph import StateGraph
from loguru import logger

from models.state import State
from services.graph.events import StopEvent
from services.graph.exceptions import NodeExecutionError, StopSession
from services.run_python_code_service import (
    CORRELATION_ID_KEY,
    TIMEOUT_RETURNCODE,
    TIMEOUT_STDERR_MESSAGE,
)

from src.crew.services.graph.subgraphs.decision_table_node import (
    DecisionTableNodeSubgraph,
)
from src.crew.tests.graph.subgraphs.sandbox_wrapper_runner import (
    SandboxWrapperRunCodeService,
)
from src.shared.models import ConditionData, ConditionGroupData, DecisionTableNodeData

SANDBOX_REFERENCE = "0123456789ab"
UNREADABLE_RESULT_DATA = "not json: sk-live-abcdef"
_REFERENCE_PATTERN = r"[0-9a-f]{12}"


class StubRunPythonCodeService:
    """Return a fixed sandbox result for every run_code call."""

    def __init__(self, result: dict):
        self._result = {"execution_id": "test", "stdout": "", **result}

    async def run_code(
        self,
        python_code_data,
        inputs,
        additional_global_kwargs=None,
        stop_event=None,
        storage_credentials=None,
    ):
        return dict(self._result)


class RaisingRunPythonCodeService:
    def __init__(self, error: BaseException):
        self._error = error

    async def run_code(self, *args, **kwargs):
        raise self._error


SANDBOX_UNAVAILABLE = StubRunPythonCodeService(
    {
        "returncode": 1,
        "stderr": f"Node execution failed (reference: {SANDBOX_REFERENCE})",
        "result_data": None,
        CORRELATION_ID_KEY: SANDBOX_REFERENCE,
    }
)
RESULT_TIMED_OUT = StubRunPythonCodeService(
    {"returncode": TIMEOUT_RETURNCODE, "stderr": TIMEOUT_STDERR_MESSAGE, "result_data": None}
)
UNREADABLE_RESULT = StubRunPythonCodeService(
    {"returncode": 0, "stderr": "", "result_data": UNREADABLE_RESULT_DATA}
)


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


def error_details(redis_service: MagicMock) -> list[str]:
    return [
        message["details"]
        for message in published_messages(redis_service)
        if message["message_type"] == "error"
    ]


def complex_group(
    expression: str, next_node: str = "node_A", manipulation: str | None = None
) -> ConditionGroupData:
    return ConditionGroupData(
        group_name="High score",
        group_type="complex",
        expression=expression,
        manipulation=manipulation,
        next_node=next_node,
    )


def table(*groups: ConditionGroupData, next_error_node: str | None = "error_node"):
    return DecisionTableNodeData(
        node_name="dt_node",
        conditional_group_list=list(groups),
        default_next_node="fallback",
        next_error_node=next_error_node,
    )


def capture_logs() -> tuple[list[str], int]:
    logged: list[str] = []
    return logged, logger.add(logged.append, level="WARNING")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("group", "variables", "expected_route", "expected_variables"),
    [
        pytest.param(
            complex_group("variables.score > 10", manipulation="variables.level = 'high'"),
            {"score": 11, "level": None},
            "node_A",
            {"level": "high"},
            id="matching-condition-runs-manipulation-and-routes",
        ),
        pytest.param(
            complex_group("variables.score > 10"),
            {"score": 3},
            "fallback",
            {},
            id="no-match-routes-to-default",
        ),
        pytest.param(
            complex_group("  variables.score > 10"),
            {"score": 11},
            "node_A",
            {},
            id="expression-with-leading-spaces",
        ),
        pytest.param(
            complex_group('json.loads(variables.payload)["kind"] == "order"'),
            {"payload": '{"kind": "order"}'},
            "node_A",
            {},
            id="expression-sees-sandbox-module-globals",
        ),
        pytest.param(
            ConditionGroupData(
                group_name="High score",
                group_type="simple",
                condition_list=[
                    ConditionData(condition="variables.score > 10"),
                    ConditionData(condition="variables.score < 20"),
                ],
                next_node="node_A",
            ),
            {"score": 15},
            "node_A",
            {},
            id="simple-group-needs-every-condition",
        ),
    ],
)
async def test_routing(group, variables, expected_route, expected_variables):
    subgraph, redis_service = build_subgraph(table(group), SandboxWrapperRunCodeService())

    result = await subgraph.ainvoke(make_state(variables))

    assert result["system_variables"]["nodes"]["dt_node"]["result_node"] == expected_route
    assert {name: result["variables"][name] for name in expected_variables} == expected_variables
    assert error_details(redis_service) == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("group", "expected_error"),
    [
        pytest.param(
            complex_group("scroe > 1"),
            "Condition \"High score\": name 'scroe' is not defined",
            id="name-error-without-line-number",
        ),
        pytest.param(
            complex_group("variables.score >"),
            'Condition "High score": invalid syntax',
            id="syntax-error",
        ),
        pytest.param(
            complex_group("variables['missing'] == 1"),
            "Condition \"High score\": key 'missing' doesn't exist",
            id="key-error",
        ),
        pytest.param(
            complex_group("variables.score"),
            'Condition "High score" must give true or false.',
            id="not-boolean",
        ),
        pytest.param(
            complex_group("True", manipulation="variables.total = totl + 1"),
            "Condition \"High score\", manipulation code: NameError on line 1: "
            "name 'totl' is not defined",
            id="manipulation-keeps-the-users-line-number",
        ),
        pytest.param(
            # Only the first line is indented for the user, so further lines need their own.
            complex_group(
                "True",
                manipulation="variables.a = 1\n    variables.b = 2\n    variables.c = total",
            ),
            "Condition \"High score\", manipulation code: NameError on line 3: "
            "name 'total' is not defined",
            id="manipulation-line-three",
        ),
        pytest.param(
            complex_group("exit()"),
            'Condition "High score" stopped the code with exit().',
            id="exit",
        ),
        pytest.param(
            complex_group("True", manipulation='raise ValueError("a\\nb")'),
            'Condition "High score", manipulation code: ValueError on line 1: a\nb',
            id="manipulation-multi-line-message",
        ),
        pytest.param(
            complex_group(
                "True",
                manipulation="import sys\n"
                "    print('ValueError on line 9: printed', file=sys.stderr)\n"
                '    raise ValueError("a\\nb")',
            ),
            'Condition "High score", manipulation code: ValueError on line 3: a\nb',
            id="manipulation-leaves-out-what-the-code-printed",
        ),
    ],
)
async def test_condition_error_is_shown_against_the_condition(group, expected_error):
    subgraph, redis_service = build_subgraph(table(group), SandboxWrapperRunCodeService())

    result = await subgraph.ainvoke(make_state({"score": 5}))

    assert error_details(redis_service) == [expected_error]
    assert result["system_variables"]["nodes"]["dt_node"]["result_node"] == "error_node"
    message_types = [message["message_type"] for message in published_messages(redis_service)]
    assert message_types[-2:] == ["error", "finish"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "group",
    [
        pytest.param(complex_group("True"), id="condition"),
        pytest.param(
            # The condition itself passes through the wrapper; the stub then fails the manipulation.
            complex_group("True", manipulation="variables.a = 1"),
            id="manipulation",
        ),
    ],
)
@pytest.mark.parametrize(
    ("failing_service", "expected_error"),
    [
        pytest.param(
            SANDBOX_UNAVAILABLE,
            'Condition "High score": the code couldn\'t run because of a server error. '
            f"Try again or contact your administrator (reference: {SANDBOX_REFERENCE}).",
            id="sandbox-unavailable",
        ),
        pytest.param(
            RESULT_TIMED_OUT,
            'Condition "High score": the code\'s result didn\'t arrive in time. '
            "Try again or contact your administrator.",
            id="result-timed-out",
        ),
    ],
)
async def test_sandbox_failure_is_shown_against_the_condition(
    group, failing_service, expected_error
):
    service = failing_service
    if group.manipulation is not None:
        service = ConditionPassesThenFails(failing_service)
    subgraph, redis_service = build_subgraph(table(group), service)

    await subgraph.ainvoke(make_state())

    assert error_details(redis_service) == [expected_error]


class ConditionPassesThenFails:
    """Run the condition for real, then answer every later call from `then`."""

    def __init__(self, then):
        self._real = SandboxWrapperRunCodeService()
        self._then = then

    async def run_code(self, python_code_data, inputs, **kwargs):
        if "expression" in inputs:
            return await self._real.run_code(python_code_data, inputs, **kwargs)
        return await self._then.run_code(python_code_data, inputs, **kwargs)


@pytest.mark.asyncio
async def test_unreadable_result_cites_a_new_reference_and_logs_the_raw_result():
    subgraph, redis_service = build_subgraph(table(complex_group("True")), UNREADABLE_RESULT)
    logged, sink_id = capture_logs()
    try:
        await subgraph.ainvoke(make_state())
    finally:
        logger.remove(sink_id)

    [details] = error_details(redis_service)
    match = re.fullmatch(
        'Condition "High score": the code couldn\'t run because of a server error. '
        rf"Try again or contact your administrator \(reference: ({_REFERENCE_PATTERN})\)\.",
        details,
    )
    assert match is not None, details
    assert match.group(1) != SANDBOX_REFERENCE
    assert any(UNREADABLE_RESULT_DATA in line and match.group(1) in line for line in logged)


@pytest.mark.asyncio
async def test_unexpected_error_shows_a_reference_and_logs_the_exception_text():
    sensitive_text = "sk-live-abcdef at https://internal.epicstaff.local"
    subgraph, redis_service = build_subgraph(
        table(complex_group("True")), RaisingRunPythonCodeService(RuntimeError(sensitive_text))
    )
    logged, sink_id = capture_logs()
    try:
        result = await subgraph.ainvoke(make_state())
    finally:
        logger.remove(sink_id)

    [details] = error_details(redis_service)
    match = re.fullmatch(rf"Node execution failed \(reference: ({_REFERENCE_PATTERN})\)", details)
    assert match is not None, details
    assert result["system_variables"]["nodes"]["dt_node"]["result_node"] == "error_node"
    assert any(sensitive_text in line and match.group(1) in line for line in logged)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("service", "expected_message", "expected_correlation_id"),
    [
        pytest.param(
            SandboxWrapperRunCodeService(),
            "Condition \"High score\": name 'scroe' is not defined",
            None,
            id="condition-error",
        ),
        pytest.param(
            SANDBOX_UNAVAILABLE,
            'Condition "High score": the code couldn\'t run because of a server error. '
            f"Try again or contact your administrator (reference: {SANDBOX_REFERENCE}).",
            SANDBOX_REFERENCE,
            id="sandbox-unavailable",
        ),
    ],
)
async def test_without_an_error_route_the_session_fails_with_the_shown_error(
    service, expected_message, expected_correlation_id
):
    subgraph, redis_service = build_subgraph(
        table(complex_group("scroe > 1"), next_error_node=None), service
    )

    with pytest.raises(NodeExecutionError) as raised:
        await subgraph.ainvoke(make_state())

    assert raised.value.public_message == expected_message
    assert raised.value.correlation_id == expected_correlation_id
    assert error_details(redis_service) == [expected_message]
    message_types = [message["message_type"] for message in published_messages(redis_service)]
    assert "finish" not in message_types


@pytest.mark.asyncio
async def test_without_an_error_route_an_unexpected_error_fails_the_session_under_its_reference():
    subgraph, redis_service = build_subgraph(
        table(complex_group("True"), next_error_node=None),
        RaisingRunPythonCodeService(RuntimeError("boom")),
    )

    with pytest.raises(NodeExecutionError) as raised:
        await subgraph.ainvoke(make_state())

    assert raised.value.public_message == (
        f"Node execution failed (reference: {raised.value.correlation_id})"
    )
    assert error_details(redis_service) == [raised.value.public_message]


@pytest.mark.asyncio
async def test_stop_is_not_reported_as_a_node_error():
    subgraph, redis_service = build_subgraph(
        table(complex_group("True")), RaisingRunPythonCodeService(StopSession())
    )

    with pytest.raises(StopSession):
        await subgraph.ainvoke(make_state())

    assert error_details(redis_service) == []
