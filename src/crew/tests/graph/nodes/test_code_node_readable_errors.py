"""Python and Webhook Trigger nodes tell the user, in words, why their code gave no result.

The code runs through the sandbox's own wrapper (`run_in_sandbox_wrapper`), so the
messages are checked against the stderr the sandbox really writes.
"""

import pytest
from dotdict import DotDict

from models.graph_models import GraphMessage
from services.graph.events import StopEvent
from services.graph.exceptions import NodeExecutionError
from services.graph.graph_session_manager_service import GraphSessionManagerService
from services.graph.nodes.python_node import PythonNode
from services.graph.nodes.webhook_trigger_node import WebhookTriggerNode
from services.run_python_code_service import TIMEOUT_RETURNCODE, TIMEOUT_STDERR_MESSAGE
from src.shared.models import PythonCodeData
from tests.graph.subgraphs.sandbox_wrapper_runner import SandboxWrapperRunCodeService

pytestmark = pytest.mark.asyncio

TIMEOUT_TEXT = "The code's result didn't arrive in time. Try again or contact your administrator."


class TimedOutRunCodeService:
    """Stands in for RunPythonCodeService when it gave up waiting for the sandbox's result."""

    async def run_code(self, python_code_data, inputs, **kwargs):
        return {
            "execution_id": "test",
            "returncode": TIMEOUT_RETURNCODE,
            "stdout": "",
            "stderr": TIMEOUT_STDERR_MESSAGE,
            "result_data": None,
        }


def python_node(
    code: str,
    service=None,
    input_map: dict | None = None,
    output_variable_path: str = "variables.result",
) -> PythonNode:
    return PythonNode(
        session_id=5,
        node_name="Clean data #2 #4512",
        stop_event=StopEvent(),
        input_map=input_map or {},
        output_variable_path=output_variable_path,
        python_code_executor_service=service or SandboxWrapperRunCodeService(),
        python_code_data=PythonCodeData(code=code, entrypoint="main"),
    )


def build_state(**variables) -> dict:
    return {"variables": DotDict(variables), "state_history": [], "system_variables": {}}


async def run_failing(node, state=None) -> tuple[NodeExecutionError, list[str]]:
    messages: list[GraphMessage] = []
    with pytest.raises(NodeExecutionError) as raised:
        await node.run(state or build_state(), writer=messages.append)
    cards = [
        message.message_data.details
        for message in messages
        if getattr(message.message_data, "message_type", None) == "error"
    ]
    return raised.value, cards


def session_error(error: NodeExecutionError) -> str:
    return GraphSessionManagerService._public_session_error(5, error)


async def test_input_main_has_no_parameter_for_is_named():
    node = python_node("def main(x):\n    return x\n", input_map={"x": "variables.x", "y": "variables.y"})

    error, cards = await run_failing(node, build_state(x=1, y=2))

    expected = 'Input "y" isn\'t a parameter of main(). Add it to main, or remove it from the input map.'
    assert cards == [expected]
    assert session_error(error) == expected


async def test_unexpected_argument_raised_inside_the_users_code_keeps_the_sandbox_text():
    # The same TypeError from a call the user's code made is the user's own error.
    node = python_node("def helper():\n    return 1\n\ndef main():\n    return helper(y=1)\n")

    _, cards = await run_failing(node)

    assert [card.strip() for card in cards] == [
        "TypeError on line 5: helper() got an unexpected keyword argument 'y'"
    ]


@pytest.mark.parametrize(
    "output_variable_path",
    ["variables.records[5]", "variables.records[5].name", "variables.count.value", "variables.count[0]"],
)
async def test_output_path_that_doesnt_exist_is_named(output_variable_path):
    node = python_node("def main():\n    return 1\n", output_variable_path=output_variable_path)

    error, cards = await run_failing(node, build_state(records=[{"name": "a"}], count=3))

    expected = (
        f'Output path "{output_variable_path}" of Python node "Clean data #2" doesn\'t exist. '
        "Check the output variable path."
    )
    assert cards == [expected]
    assert session_error(error) == expected


async def test_output_path_that_can_be_created_is_still_stored():
    node = python_node("def main():\n    return 7\n", output_variable_path="variables.report.total")

    state = await node.run(build_state(records=[]), writer=lambda message: None)

    assert state["variables"].deep_dump() == {"records": [], "report": {"total": 7}}


async def test_python_node_result_that_never_arrived_says_so():
    node = python_node("def main():\n    return 1\n", service=TimedOutRunCodeService())

    error, cards = await run_failing(node)

    assert cards == [TIMEOUT_TEXT]
    assert session_error(error) == TIMEOUT_TEXT


async def test_webhook_trigger_result_that_never_arrived_says_so():
    node = WebhookTriggerNode(
        session_id=5,
        node_name="Order received #1 #45",
        stop_event=StopEvent(),
        python_code_executor_service=TimedOutRunCodeService(),
        python_code_data=PythonCodeData(code="def main(**kwargs):\n    return {}\n", entrypoint="main"),
    )

    error, cards = await run_failing(node)

    assert cards == [TIMEOUT_TEXT]
    assert session_error(error) == TIMEOUT_TEXT


async def test_webhook_trigger_unexpected_argument_keeps_the_sandbox_text():
    # The webhook's inputs are the whole flow state, so there is no input map to fix.
    node = WebhookTriggerNode(
        session_id=5,
        node_name="Order received #1 #45",
        stop_event=StopEvent(),
        python_code_executor_service=SandboxWrapperRunCodeService(),
        python_code_data=PythonCodeData(code="def main():\n    return {}\n", entrypoint="main"),
    )

    _, cards = await run_failing(node, build_state(order=1))

    assert [card.strip() for card in cards] == [
        "TypeError: main() got an unexpected keyword argument 'order'"
    ]


async def test_progress_text_names_the_node_without_its_id():
    messages: list[GraphMessage] = []
    node = python_node("def main():\n    return 1\n")

    await node.run(build_state(), writer=messages.append)

    progress = [
        message.message_data["text"]
        for message in messages
        if isinstance(message.message_data, dict)
        and message.message_data.get("message_type") == "python_stream"
    ]
    assert progress == ["Executing 'Clean data #2'..."]
