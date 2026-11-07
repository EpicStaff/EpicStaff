"""Python and Webhook Trigger nodes tell the user, in words, why their code gave no result.

The nodes get the results the sandbox sends (`tests.graph.code_results`); which failure
the sandbox reports for which code is the sandbox's own tests' concern.
"""

import pytest
from dotdict import DotDict

from models.graph_models import GraphMessage, PythonMessageData
from services.graph.events import StopEvent
from services.graph.exceptions import NodeExecutionError
from services.graph.graph_session_manager_service import GraphSessionManagerService
from services.graph.nodes.python_node import PythonNode
from services.graph.nodes.webhook_trigger_node import WebhookTriggerNode
from src.shared.models import CodeFailure, CodeFailureCode, PythonCodeData
from tests.graph.code_results import (
    CannedRunCodeService,
    failed,
    succeeded,
    user_code_failure,
)

pytestmark = pytest.mark.asyncio

TIMEOUT_TEXT = "The code's result didn't arrive in time. Try again or contact your administrator."
TIMED_OUT = failed(CodeFailure(code=CodeFailureCode.RESULT_TIMEOUT, detail=TIMEOUT_TEXT))


def python_node(
    service,
    input_map: dict | None = None,
    output_variable_path: str = "variables.result",
) -> PythonNode:
    return PythonNode(
        session_id=5,
        node_name="Clean data #2 #4512",
        stop_event=StopEvent(),
        input_map=input_map or {},
        output_variable_path=output_variable_path,
        python_code_executor_service=service,
        python_code_data=PythonCodeData(code="def main(x):\n    return x\n", entrypoint="main"),
    )


def webhook_trigger_node(service) -> WebhookTriggerNode:
    return WebhookTriggerNode(
        session_id=5,
        node_name="Order received #1 #45",
        stop_event=StopEvent(),
        python_code_executor_service=service,
        python_code_data=PythonCodeData(code="def main():\n    return {}\n", entrypoint="main"),
    )


def build_state(**variables) -> dict:
    return {"variables": DotDict(variables), "state_history": [], "system_variables": {}}


async def run_failing(node, state=None) -> tuple[NodeExecutionError, list[str], list[dict]]:
    """Run `node`, expecting it to fail; return the error, error cards and shown code results."""
    messages: list[GraphMessage] = []
    with pytest.raises(NodeExecutionError) as raised:
        await node.run(state or build_state(), writer=messages.append)
    cards = [
        message.message_data.details
        for message in messages
        if getattr(message.message_data, "message_type", None) == "error"
    ]
    shown_results = [
        message.message_data.python_code_execution_data
        for message in messages
        if isinstance(message.message_data, PythonMessageData)
    ]
    return raised.value, cards, shown_results


def session_error(error: NodeExecutionError) -> str:
    return GraphSessionManagerService._public_session_error(5, error)


async def test_input_main_has_no_parameter_for_is_named():
    service = CannedRunCodeService(
        failed(
            CodeFailure(
                code=CodeFailureCode.UNEXPECTED_ARGUMENT,
                detail="TypeError: main() got an unexpected keyword argument 'y'",
                attr="y",
            )
        )
    )
    node = python_node(service, input_map={"x": "variables.x", "y": "variables.y"})

    error, cards, _ = await run_failing(node, build_state(x=1, y=2))

    expected = 'Input "y" isn\'t a parameter of main(). Add it to main, or remove it from the input map.'
    assert cards == [expected]
    assert session_error(error) == expected


@pytest.mark.parametrize(
    "failure",
    [
        pytest.param(
            # The same TypeError from a call the user's code made is the user's own error.
            user_code_failure("TypeError", 5, "helper() got an unexpected keyword argument 'y'"),
            id="unexpected-argument-inside-the-code",
        ),
        pytest.param(
            CodeFailure(
                code=CodeFailureCode.MISSING_ARGUMENT,
                detail="TypeError: main() missing 1 required positional argument: 'x'",
                attr="x",
            ),
            id="missing-argument",
        ),
        pytest.param(
            CodeFailure(
                code=CodeFailureCode.CODE_EXITED,
                detail="The code exited with code 3 before it returned a result.",
            ),
            id="code-exited",
        ),
    ],
)
async def test_failure_of_the_code_shows_its_detail(failure):
    _, cards, _ = await run_failing(python_node(CannedRunCodeService(failed(failure))))

    assert cards == [failure.detail]


async def test_error_shows_the_failure_while_the_python_message_keeps_the_whole_stderr():
    failure = user_code_failure("KeyError", 4, "'rows'")
    result = failed(failure, printed="loading rows\n")

    _, cards, shown_results = await run_failing(python_node(CannedRunCodeService(result)))

    assert cards == ["KeyError on line 4: 'rows'"]
    assert [shown["stderr"] for shown in shown_results] == ["loading rows\nKeyError on line 4: 'rows'"]


@pytest.mark.parametrize(
    "output_variable_path",
    ["variables.records[5]", "variables.records[5].name", "variables.count.value", "variables.count[0]"],
)
async def test_output_path_that_doesnt_exist_is_named(output_variable_path):
    node = python_node(CannedRunCodeService(succeeded(1)), output_variable_path=output_variable_path)

    error, cards, _ = await run_failing(node, build_state(records=[{"name": "a"}], count=3))

    expected = (
        f'Output path "{output_variable_path}" of Python node "Clean data #2" doesn\'t exist. '
        "Check the output variable path."
    )
    assert cards == [expected]
    assert session_error(error) == expected


async def test_output_path_that_can_be_created_is_still_stored():
    node = python_node(CannedRunCodeService(succeeded(7)), output_variable_path="variables.report.total")

    state = await node.run(build_state(records=[]), writer=lambda message: None)

    assert state["variables"].deep_dump() == {"records": [], "report": {"total": 7}}


async def test_python_node_result_that_never_arrived_says_so():
    error, cards, _ = await run_failing(python_node(CannedRunCodeService(TIMED_OUT)))

    assert cards == [TIMEOUT_TEXT]
    assert session_error(error) == TIMEOUT_TEXT


async def test_webhook_trigger_result_that_never_arrived_says_so():
    error, cards, _ = await run_failing(webhook_trigger_node(CannedRunCodeService(TIMED_OUT)))

    assert cards == [TIMEOUT_TEXT]
    assert session_error(error) == TIMEOUT_TEXT


async def test_webhook_trigger_unexpected_argument_keeps_the_sandbox_text():
    # The webhook's inputs are the whole flow state, so there is no input map to fix.
    detail = "TypeError: main() got an unexpected keyword argument 'order'"
    service = CannedRunCodeService(
        failed(CodeFailure(code=CodeFailureCode.UNEXPECTED_ARGUMENT, detail=detail, attr="order"))
    )

    _, cards, _ = await run_failing(webhook_trigger_node(service), build_state(order=1))

    assert cards == [detail]


async def test_progress_text_names_the_node_without_its_id():
    messages: list[GraphMessage] = []
    node = python_node(CannedRunCodeService(succeeded(1)))

    await node.run(build_state(), writer=messages.append)

    progress = [
        message.message_data["text"]
        for message in messages
        if isinstance(message.message_data, dict)
        and message.message_data.get("message_type") == "python_stream"
    ]
    assert progress == ["Executing 'Clean data #2'..."]
