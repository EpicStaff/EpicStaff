"""A code node whose sandbox couldn't run the code shows a reference, never the raw reason.

The nodes run against the real RunPythonCodeService and SandboxClient over the
FakeSandbox, so the raw text starts where it does in production: the sandbox's HTTP
answer. A failure the sandbox reports names the node and passes the sandbox's reference
on; a failure of the user's own code shows the failure's detail.
"""

import asyncio
import json

import pytest
from dotdict import DotDict
from loguru import logger

from models.graph_models import GraphMessage
from services.graph.events import StopEvent
from services.graph.exceptions import NodeExecutionError
from services.graph.graph_session_manager_service import GraphSessionManagerService
from services.graph.nodes.python_node import PythonNode
from services.graph.nodes.webhook_trigger_node import WebhookTriggerNode
from src.shared.models import CodeFailure, CodeFailureCode, CodeResultData, UserCodeError
from tests.services.conftest import CREW_RESULT_CHANNEL

pytestmark = pytest.mark.asyncio

REFERENCE = "0a1b2c3d4e5f"
# A reference the sandbox minted and logged under; crew only passes it on.
SANDBOX_REFERENCE = "9f8e7d6c5b4a"
RAW_SANDBOX_BODY = "<html>500 at sandbox-internal:8000, venv /opt/venvs/org-7</html>"


@pytest.fixture
def fixed_reference(monkeypatch):
    monkeypatch.setattr("foundation.utils.error_reference.new_reference", lambda: REFERENCE)


@pytest.fixture
def captured_error_logs():
    records: list[str] = []
    sink_id = logger.add(records.append, level="ERROR")
    yield records
    logger.remove(sink_id)


def python_node(service, make_python_code_data) -> PythonNode:
    return PythonNode(
        session_id=5,
        node_name="Clean data #2 #44",
        stop_event=StopEvent(),
        input_map={},
        output_variable_path="variables",
        python_code_executor_service=service,
        python_code_data=make_python_code_data(),
    )


def webhook_trigger_node(service, make_python_code_data) -> WebhookTriggerNode:
    return WebhookTriggerNode(
        session_id=5,
        node_name="Order received #1 #45",
        stop_event=StopEvent(),
        python_code_executor_service=service,
        python_code_data=make_python_code_data(),
    )


def state() -> dict:
    return {"variables": DotDict({}), "state_history": [], "system_variables": {}}


async def run_failing(node) -> tuple[NodeExecutionError, list[GraphMessage]]:
    messages: list[GraphMessage] = []
    with pytest.raises(NodeExecutionError) as raised:
        await asyncio.wait_for(node.run(state(), messages.append), timeout=5)
    return raised.value, messages


def error_cards(messages: list[GraphMessage]) -> list[str]:
    return [
        message.message_data.details
        for message in messages
        if getattr(message.message_data, "message_type", None) == "error"
    ]


@pytest.mark.parametrize(
    ("build_node", "expected_message"),
    [
        (
            python_node,
            'Python node "Clean data #2" couldn\'t run its code. '
            f"Try again or contact your administrator (reference: {REFERENCE}).",
        ),
        (
            webhook_trigger_node,
            'Webhook Trigger node "Order received #1" couldn\'t run its code. '
            f"Try again or contact your administrator (reference: {REFERENCE}).",
        ),
    ],
    ids=["python", "webhook-trigger"],
)
async def test_sandbox_failure_shows_a_reference_and_logs_the_raw_reason_under_it(
    run_python_code_service,
    sandbox,
    make_python_code_data,
    fixed_reference,
    captured_error_logs,
    build_node,
    expected_message,
):
    sandbox.rejects_with = RAW_SANDBOX_BODY

    error, messages = await run_failing(build_node(run_python_code_service, make_python_code_data))

    assert error_cards(messages) == [expected_message]
    assert error.public_message == expected_message
    assert error.reference == REFERENCE
    for message in messages:
        assert RAW_SANDBOX_BODY not in json.dumps(message.message_data, default=vars)
    [logged] = [
        record for record in captured_error_logs if f"(reference: {REFERENCE})" in record
    ]
    assert RAW_SANDBOX_BODY in logged


async def run_python_node_answered_with(
    service, sandbox, make_python_code_data, **result_fields
) -> tuple[NodeExecutionError, list[GraphMessage]]:
    """Run a Python node whose execution the sandbox answers with `result_fields`."""
    running = asyncio.ensure_future(run_failing(python_node(service, make_python_code_data)))
    [task] = await sandbox.wait_for_tasks(1)
    await sandbox.pubsub.apublish(
        CREW_RESULT_CHANNEL,
        CodeResultData(
            execution_id=task["execution_id"], stdout="", **result_fields
        ).model_dump_json(),
    )
    return await running


async def test_failure_of_the_users_code_shows_only_the_failures_detail(
    run_python_code_service, sandbox, make_python_code_data, fixed_reference
):
    detail = "NameError on line 3: name 'rows' is not defined"
    error, messages = await run_python_node_answered_with(
        run_python_code_service,
        sandbox,
        make_python_code_data,
        returncode=1,
        # What the code printed before it failed stays in the Python message only.
        stderr=f"loading rows\n{detail}",
        failure=CodeFailure(
            code=CodeFailureCode.USER_CODE_ERROR,
            detail=detail,
            user_error=UserCodeError(
                exception_type="NameError", line=3, message="name 'rows' is not defined"
            ),
        ),
    )

    assert error_cards(messages) == [detail]
    assert error.public_message == detail
    assert error.reference is None


@pytest.mark.parametrize(
    ("code", "sandbox_detail", "expected_message"),
    [
        pytest.param(
            CodeFailureCode.SANDBOX_ERROR,
            "The code couldn't run because of a server error. Try again or contact your "
            f"administrator (reference: {SANDBOX_REFERENCE}).",
            'Python node "Clean data #2" couldn\'t run its code. '
            f"Try again or contact your administrator (reference: {SANDBOX_REFERENCE}).",
            id="sandbox-error",
        ),
        pytest.param(
            CodeFailureCode.DISPATCH_FAILED,
            "The code couldn't run because of a server error. Try again or contact your "
            f"administrator (reference: {SANDBOX_REFERENCE}).",
            'Python node "Clean data #2" couldn\'t run its code. '
            f"Try again or contact your administrator (reference: {SANDBOX_REFERENCE}).",
            id="dispatch-failed",
        ),
        pytest.param(
            CodeFailureCode.UNSAFE_TO_RUN,
            "This server can't run code safely right now, so the code wasn't run. Contact "
            f"your administrator (reference: {SANDBOX_REFERENCE}).",
            'Python node "Clean data #2" couldn\'t run its code: this server can\'t run code '
            f"safely right now. Contact your administrator (reference: {SANDBOX_REFERENCE}).",
            id="unsafe-to-run",
        ),
    ],
)
async def test_sandbox_failure_names_the_node_and_carries_the_sandbox_reference(
    run_python_code_service, sandbox, make_python_code_data, code, sandbox_detail, expected_message
):
    error, messages = await run_python_node_answered_with(
        run_python_code_service,
        sandbox,
        make_python_code_data,
        returncode=1,
        stderr=sandbox_detail,
        failure=CodeFailure(code=code, detail=sandbox_detail),
        reference=SANDBOX_REFERENCE,
    )

    assert error_cards(messages) == [expected_message]
    assert error.reference == SANDBOX_REFERENCE
    assert GraphSessionManagerService._public_session_error(5, error) == (
        "The flow failed. Try again or contact your administrator "
        f"(reference: {SANDBOX_REFERENCE})."
    )


async def test_failed_result_without_a_failure_is_logged_as_a_broken_contract(
    run_python_code_service, sandbox, make_python_code_data, fixed_reference, captured_error_logs
):
    error, messages = await run_python_node_answered_with(
        run_python_code_service,
        sandbox,
        make_python_code_data,
        returncode=3,
        stderr="raw output of the code",
    )

    expected_message = (
        'Python node "Clean data #2" couldn\'t run its code. '
        f"Try again or contact your administrator (reference: {REFERENCE})."
    )
    assert error_cards(messages) == [expected_message]
    assert error.reference == REFERENCE
    [logged] = [record for record in captured_error_logs if f"(reference: {REFERENCE})" in record]
    assert "failed with return code 3 but reported no failure" in logged
    assert "raw output of the code" not in logged
