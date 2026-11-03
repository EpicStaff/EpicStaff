"""A code node whose sandbox couldn't run the code shows a reference, never the raw reason.

The nodes run against the real RunPythonCodeService and SandboxClient over the
FakeSandbox, so the raw text starts where it does in production: the sandbox's HTTP
answer. A failure of the user's own code still shows its stderr.
"""

import asyncio
import json

import pytest
from dotdict import DotDict
from loguru import logger

from models.graph_models import GraphMessage
from services import run_python_code_service as run_python_code_service_module
from services.graph.events import StopEvent
from services.graph.exceptions import NodeExecutionError
from services.graph.nodes import base_node
from services.graph.nodes.python_node import PythonNode
from services.graph.nodes.webhook_trigger_node import WebhookTriggerNode
from src.shared.models import CodeResultData
from tests.services.conftest import CREW_RESULT_CHANNEL

pytestmark = pytest.mark.asyncio

REFERENCE = "0a1b2c3d4e5f"
RAW_SANDBOX_BODY = "<html>500 at sandbox-internal:8000, venv /opt/venvs/org-7</html>"


@pytest.fixture
def fixed_reference(monkeypatch):
    for module in (run_python_code_service_module, base_node):
        monkeypatch.setattr(module, "new_error_correlation_id", lambda: REFERENCE)


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
    assert error.correlation_id == REFERENCE
    for message in messages:
        assert RAW_SANDBOX_BODY not in json.dumps(message.message_data, default=vars)
    [logged] = [record for record in captured_error_logs if REFERENCE in record]
    assert RAW_SANDBOX_BODY in logged


async def test_failure_of_the_users_code_still_shows_its_stderr(
    run_python_code_service, sandbox, make_python_code_data, fixed_reference
):
    user_stderr = "NameError: name 'rows' is not defined"
    node = python_node(run_python_code_service, make_python_code_data)
    running = asyncio.ensure_future(run_failing(node))
    [task] = await sandbox.wait_for_tasks(1)
    await sandbox.pubsub.apublish(
        CREW_RESULT_CHANNEL,
        CodeResultData(
            execution_id=task["execution_id"],
            stderr=user_stderr,
            stdout="",
            returncode=1,
        ).model_dump_json(),
    )

    error, messages = await running

    assert error_cards(messages) == [user_stderr]
    assert error.public_message == user_stderr
    assert error.correlation_id is None
