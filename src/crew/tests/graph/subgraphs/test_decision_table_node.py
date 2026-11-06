"""Tests for DecisionTableNodeSubgraph routing and the errors it shows the user.

The code the node generates runs for real (`GeneratedCodeRunCodeService`), so conditions
and manipulations give the results they really give. A failure is the result the sandbox
sends for it (`tests.graph.code_results`): the user's error on a line of the code the node
sent, or a failure of the sandbox or of crew's wait for the result.
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
from src.crew.services.graph.subgraphs.decision_table_node import (
    DecisionTableNodeSubgraph,
)
from src.shared.models import (
    CodeFailure,
    CodeFailureCode,
    CodeResultData,
    ConditionData,
    ConditionGroupData,
    DecisionTableNodeData,
)
from tests.graph.code_results import CannedRunCodeService, failed, raised_on
from tests.graph.generated_code_runner import GeneratedCodeRunCodeService

SANDBOX_REFERENCE = "0123456789ab"
UNREADABLE_RESULT_DATA = "not json: sk-live-abcdef"
_REFERENCE_PATTERN = r"[0-9a-f]{12}"


class RaisingRunPythonCodeService:
    def __init__(self, error: BaseException):
        self._error = error

    async def run_code(self, *args, **kwargs):
        raise self._error


SANDBOX_UNAVAILABLE = failed(
    CodeFailure(
        code=CodeFailureCode.SANDBOX_ERROR,
        detail=f"Node execution failed (reference: {SANDBOX_REFERENCE})",
    ),
    reference=SANDBOX_REFERENCE,
)
UNSAFE_TO_RUN = failed(
    CodeFailure(
        code=CodeFailureCode.UNSAFE_TO_RUN,
        detail="This server can't run code safely right now, so the code wasn't run. Contact "
        f"your administrator (reference: {SANDBOX_REFERENCE}).",
    ),
    reference=SANDBOX_REFERENCE,
)
RESULT_TIMED_OUT = failed(
    CodeFailure(
        code=CodeFailureCode.RESULT_TIMEOUT,
        detail="The code's result didn't arrive in time. Try again or contact your administrator.",
    )
)
UNREADABLE_RESULT = CodeResultData(
    execution_id="test", returncode=0, stdout="", stderr="", result_data=UNREADABLE_RESULT_DATA
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
    subgraph, redis_service = build_subgraph(table(group), GeneratedCodeRunCodeService())

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
            complex_group("exit()"),
            'Condition "High score" stopped the code with exit().',
            id="exit",
        ),
    ],
)
async def test_condition_error_is_shown_against_the_condition(group, expected_error):
    subgraph, redis_service = build_subgraph(table(group), GeneratedCodeRunCodeService())

    result = await subgraph.ainvoke(make_state({"score": 5}))

    assert error_details(redis_service) == [expected_error]
    assert result["system_variables"]["nodes"]["dt_node"]["result_node"] == "error_node"
    message_types = [message["message_type"] for message in published_messages(redis_service)]
    assert message_types[-2:] == ["error", "finish"]


def manipulation_answered_with(answer) -> GeneratedCodeRunCodeService:
    """Run the conditions for real, and answer the manipulation's run with `answer(code)`."""
    return GeneratedCodeRunCodeService(
        answer=lambda python_code_data, inputs: (
            None if "expression" in inputs else answer(python_code_data.code)
        )
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("manipulation", "answer", "expected_error"),
    [
        pytest.param(
            "variables.total = totl + 1",
            lambda code: raised_on(code, "totl", "NameError", "name 'totl' is not defined"),
            "Condition \"High score\", manipulation code: NameError on line 1: "
            "name 'totl' is not defined",
            id="keeps-the-users-line-number",
        ),
        pytest.param(
            # Only the first line is indented for the user, so further lines need their own.
            "variables.a = 1\n    variables.b = 2\n    variables.c = total",
            lambda code: raised_on(
                code, "variables.c = total", "NameError", "name 'total' is not defined"
            ),
            "Condition \"High score\", manipulation code: NameError on line 3: "
            "name 'total' is not defined",
            id="line-three",
        ),
        pytest.param(
            'raise ValueError("a\\nb")',
            lambda code: raised_on(code, "raise ValueError", "ValueError", "a\nb"),
            'Condition "High score", manipulation code: ValueError on line 1: a\nb',
            id="multi-line-message",
        ),
        pytest.param(
            "import sys\n"
            "    print('ValueError on line 9: printed', file=sys.stderr)\n"
            '    raise ValueError("a\\nb")',
            lambda code: raised_on(
                code,
                "raise ValueError",
                "ValueError",
                "a\nb",
                printed="ValueError on line 9: printed\n",
            ),
            'Condition "High score", manipulation code: ValueError on line 3: a\nb',
            id="leaves-out-what-the-code-printed",
        ),
        pytest.param(
            "variables.a = 1",
            lambda code: raised_on(
                code, "return variables", "NameError", "name 'variables' is not defined"
            ),
            "Condition \"High score\", manipulation code: NameError: "
            "name 'variables' is not defined",
            id="line-of-the-generated-code-has-no-number",
        ),
        pytest.param(
            "variables.a = 1",
            lambda code: failed(
                CodeFailure(
                    code=CodeFailureCode.CODE_EXITED,
                    detail="The code exited with code 3 before it returned a result.",
                )
            ),
            'Condition "High score", manipulation code: '
            "The code exited with code 3 before it returned a result.",
            id="failure-of-another-kind-shows-its-detail",
        ),
    ],
)
async def test_manipulation_error_is_shown_against_the_users_code(
    manipulation, answer, expected_error
):
    subgraph, redis_service = build_subgraph(
        table(complex_group("True", manipulation=manipulation)),
        manipulation_answered_with(answer),
    )

    result = await subgraph.ainvoke(make_state({"score": 5}))

    assert error_details(redis_service) == [expected_error]
    assert result["system_variables"]["nodes"]["dt_node"]["result_node"] == "error_node"


@pytest.mark.asyncio
async def test_condition_the_sandbox_stopped_shows_the_failures_detail():
    detail = "The code took longer than 30 seconds and was stopped."
    service = CannedRunCodeService(
        failed(CodeFailure(code=CodeFailureCode.EXECUTION_TIMEOUT, detail=detail))
    )
    subgraph, redis_service = build_subgraph(table(complex_group("True")), service)

    await subgraph.ainvoke(make_state())

    assert error_details(redis_service) == [f'Condition "High score": {detail}']


@pytest.mark.asyncio
@pytest.mark.parametrize("part", ["condition", "manipulation"])
@pytest.mark.parametrize(
    ("failed_result", "expected_error"),
    [
        pytest.param(
            SANDBOX_UNAVAILABLE,
            'Condition "High score": the code couldn\'t run because of a server error. '
            f"Try again or contact your administrator (reference: {SANDBOX_REFERENCE}).",
            id="sandbox-unavailable",
        ),
        pytest.param(
            UNSAFE_TO_RUN,
            'Condition "High score": this server can\'t run code safely right now, so the '
            f"code wasn't run. Contact your administrator (reference: {SANDBOX_REFERENCE}).",
            id="unsafe-to-run",
        ),
        pytest.param(
            RESULT_TIMED_OUT,
            'Condition "High score": the code\'s result didn\'t arrive in time. '
            "Try again or contact your administrator.",
            id="result-timed-out",
        ),
    ],
)
async def test_sandbox_failure_is_shown_against_the_condition(part, failed_result, expected_error):
    if part == "manipulation":
        group = complex_group("True", manipulation="variables.a = 1")
        service = manipulation_answered_with(lambda code: failed_result)
    else:
        group = complex_group("True")
        service = CannedRunCodeService(failed_result)
    subgraph, redis_service = build_subgraph(table(group), service)

    await subgraph.ainvoke(make_state())

    assert error_details(redis_service) == [expected_error]


@pytest.mark.asyncio
async def test_failed_result_without_a_failure_cites_a_new_reference():
    broken = CodeResultData(
        execution_id="test", returncode=3, stdout="", stderr="raw output", result_data=None
    )
    subgraph, redis_service = build_subgraph(
        table(complex_group("True")), CannedRunCodeService(broken)
    )
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
    assert any("reported no failure" in line and match.group(1) in line for line in logged)


@pytest.mark.asyncio
async def test_unreadable_result_cites_a_new_reference_and_logs_the_raw_result():
    subgraph, redis_service = build_subgraph(
        table(complex_group("True")), CannedRunCodeService(UNREADABLE_RESULT)
    )
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
    ("service", "expected_message", "expected_reference"),
    [
        pytest.param(
            GeneratedCodeRunCodeService(),
            "Condition \"High score\": name 'scroe' is not defined",
            None,
            id="condition-error",
        ),
        pytest.param(
            CannedRunCodeService(SANDBOX_UNAVAILABLE),
            'Condition "High score": the code couldn\'t run because of a server error. '
            f"Try again or contact your administrator (reference: {SANDBOX_REFERENCE}).",
            SANDBOX_REFERENCE,
            id="sandbox-unavailable",
        ),
    ],
)
async def test_without_an_error_route_the_session_fails_with_the_shown_error(
    service, expected_message, expected_reference
):
    subgraph, redis_service = build_subgraph(
        table(complex_group("scroe > 1"), next_error_node=None), service
    )

    with pytest.raises(NodeExecutionError) as raised:
        await subgraph.ainvoke(make_state())

    assert raised.value.public_message == expected_message
    assert raised.value.reference == expected_reference
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
        f"Node execution failed (reference: {raised.value.reference})"
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
