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
from src.shared.models import (
    SERVER_FAILURE_CODES,
    CodeFailure,
    CodeFailureCode,
    CodeResultData,
    UserCodeError,
)
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


@pytest.fixture
def captured_warning_logs():
    records: list[str] = []
    sink_id = logger.add(records.append, level="WARNING")
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
    run_python_code_service,
    sandbox,
    make_python_code_data,
    captured_warning_logs,
    code,
    sandbox_detail,
    expected_message,
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
    # The sandbox logged the cause at ERROR; crew adds which run it was, at WARNING, so
    # the reference the user quotes leads to the session and node without a second alert.
    [logged] = [
        record
        for record in captured_warning_logs
        if f"(reference: {SANDBOX_REFERENCE}) Python node" in record
    ]
    assert "| WARNING" in logged
    assert 'Python node "Clean data #2" of session 5' in logged


@pytest.mark.parametrize("sandbox_reference", ["<b>x</b>", "9F8E7D6C5B4A", None])
async def test_sandbox_failure_without_a_usable_reference_cites_a_new_one(
    run_python_code_service,
    sandbox,
    make_python_code_data,
    fixed_reference,
    captured_error_logs,
    sandbox_reference,
):
    sandbox_detail = "The code couldn't run because of a server error."
    error, messages = await run_python_node_answered_with(
        run_python_code_service,
        sandbox,
        make_python_code_data,
        returncode=1,
        stderr=sandbox_detail,
        failure=CodeFailure(code=CodeFailureCode.SANDBOX_ERROR, detail=sandbox_detail),
        reference=sandbox_reference,
    )

    expected_message = (
        'Python node "Clean data #2" couldn\'t run its code. '
        f"Try again or contact your administrator (reference: {REFERENCE})."
    )
    assert error_cards(messages) == [expected_message]
    assert error.reference == REFERENCE
    [logged] = [record for record in captured_error_logs if f"(reference: {REFERENCE})" in record]
    assert "without a usable reference" in logged
    if sandbox_reference is not None:
        assert sandbox_reference not in "".join(captured_error_logs)


@pytest.mark.parametrize(
    ("stderr", "expected_message"),
    [
        pytest.param(
            "loading rows\nValueError on line 3: bad row\n",
            "ValueError on line 3: bad row",
            id="last-line",
        ),
        pytest.param("", "The code failed with exit code 3.", id="no-output"),
    ],
)
async def test_failed_result_from_an_older_sandbox_shows_the_end_of_its_stderr(
    run_python_code_service,
    sandbox,
    make_python_code_data,
    captured_warning_logs,
    stderr,
    expected_message,
):
    # An older sandbox sends no failure; its stderr ends with the failure line, which is
    # what the user saw before the failure field existed.
    error, messages = await run_python_node_answered_with(
        run_python_code_service,
        sandbox,
        make_python_code_data,
        returncode=3,
        stderr=stderr,
    )

    assert error_cards(messages) == [expected_message]
    assert error.reference is None
    [logged] = [record for record in captured_warning_logs if "reported no failure" in record]
    assert "| WARNING" in logged
    assert "bad row" not in logged


async def test_failure_of_a_code_this_version_doesnt_know_shows_its_detail(
    run_python_code_service, sandbox, make_python_code_data, captured_error_logs
):
    detail = "The code ran out of memory. Use less data."
    error, messages = await run_python_node_answered_with(
        run_python_code_service,
        sandbox,
        make_python_code_data,
        returncode=1,
        stderr=detail,
        failure=CodeFailure.model_validate({"code": "memory_exceeded", "detail": detail}),
    )

    assert error_cards(messages) == [detail]
    assert error.reference is None
    assert captured_error_logs == []


# How crew's code nodes read each failure code. Adding a code to CodeFailureCode fails
# this test until someone decides which it is.
SHOWN_AS_ITS_DETAIL = {
    CodeFailureCode.USER_CODE_ERROR,
    CodeFailureCode.MISSING_ENTRYPOINT,
    CodeFailureCode.MISSING_ARGUMENT,
    CodeFailureCode.BAD_RETURN_VALUE,
    CodeFailureCode.NETWORK_DENIED,
    CodeFailureCode.CODE_EXITED,
    CodeFailureCode.EXECUTION_TIMEOUT,
    CodeFailureCode.RESULT_TOO_LARGE,
    CodeFailureCode.OVERLOADED,
    CodeFailureCode.PACKAGE_NOT_FOUND,
    CodeFailureCode.PACKAGE_VERSION_NOT_FOUND,
    CodeFailureCode.PACKAGE_DEPENDENCY_CONFLICT,
    CodeFailureCode.PACKAGE_INSTALL_FAILED,
    CodeFailureCode.HOLD_TIMEOUT,
    CodeFailureCode.RESULT_TIMEOUT,
    CodeFailureCode.UNKNOWN,
}
# Told in words of the node's input map.
SHOWN_IN_WORDS = {CodeFailureCode.UNEXPECTED_ARGUMENT}


def test_every_failure_code_has_a_decided_reading():
    decided = SHOWN_AS_ITS_DETAIL | SHOWN_IN_WORDS | SERVER_FAILURE_CODES

    assert decided == set(CodeFailureCode)
    assert not SHOWN_AS_ITS_DETAIL & SERVER_FAILURE_CODES
