import re

import pytest
from dotdict import DotDict
from loguru import logger

from services.graph.events import StopEvent
from services.graph.exceptions import (
    EmptyKnowledgeQueryError,
    KeyValueNodeError,
    KnowledgeSearchError,
    NodeExecutionError,
    ReturnCodeError,
    StopSession,
)
from services.graph.nodes.base_node import BaseNode
from services.graph.nodes.schedule_trigger_node import ScheduleTriggerNode

SECRET_TEXT = "postgres://admin:sup3rs3cret@internal-db.epicstaff.local:5432/crewdb"
GENERIC_DETAILS_PATTERN = r"^Node execution failed \(reference: ([0-9a-f]{12})\)$"
SANDBOX_STDERR = "Traceback: NameError at /opt/crew/secret_path.py, token sk-live-abcdef"


class RaisingNode(BaseNode):
    """A node whose execute raises `error`."""

    TYPE = "PYTHON"

    def __init__(self, error: Exception, node_name: str = "leaky"):
        super().__init__(session_id=7, node_name=node_name, stop_event=StopEvent())
        self.error = error

    async def execute(self, state, writer, execution_order, input_):
        raise self.error


def build_state():
    return {
        "variables": DotDict({}),
        "state_history": [],
        "system_variables": {},
    }


def error_details(messages) -> list[str]:
    return [
        message.message_data.details
        for message in messages
        if message.message_data.message_type == "error"
    ]


async def run_failing(node: BaseNode, expected_error: type[Exception] = NodeExecutionError):
    """Run `node`, expecting it to fail; return the raised error and the streamed error texts."""
    messages = []
    with pytest.raises(expected_error) as raised:
        await node.run(build_state(), writer=messages.append)
    return raised.value, error_details(messages)


@pytest.fixture
def captured_logs():
    records: list[str] = []
    sink_id = logger.add(records.append, level="ERROR")
    yield records
    logger.remove(sink_id)


@pytest.mark.asyncio
async def test_failing_node_streams_generic_details_and_raises_them_with_the_reference(
    captured_logs,
):
    original_error = RuntimeError(f"connection refused: {SECRET_TEXT}")

    error, details = await run_failing(RaisingNode(original_error))

    assert len(details) == 1
    reference = re.fullmatch(GENERIC_DETAILS_PATTERN, details[0]).group(1)
    assert SECRET_TEXT not in details[0]
    assert error.public_message == details[0]
    assert error.correlation_id == reference
    assert error.__cause__ is original_error


@pytest.mark.asyncio
async def test_raw_error_is_logged_with_the_streamed_correlation_id(captured_logs):
    error, details = await run_failing(RaisingNode(RuntimeError(f"connection refused: {SECRET_TEXT}")))

    matching_logs = [record for record in captured_logs if error.correlation_id in record]
    assert len(matching_logs) == 1
    assert SECRET_TEXT in matching_logs[0]
    assert "leaky" in matching_logs[0]
    assert "session_id=7" in matching_logs[0]


@pytest.mark.asyncio
async def test_each_failure_gets_its_own_correlation_id(captured_logs):
    node = RaisingNode(RuntimeError(SECRET_TEXT))

    first_error, _ = await run_failing(node)
    second_error, _ = await run_failing(node)

    assert first_error.correlation_id != second_error.correlation_id


@pytest.mark.asyncio
async def test_plain_value_error_is_not_shown_to_the_user(captured_logs):
    """Marking one error type safe must not make every ValueError public."""
    error, details = await run_failing(RaisingNode(ValueError(SECRET_TEXT)))

    assert re.fullmatch(GENERIC_DETAILS_PATTERN, details[0])
    assert error.public_message == details[0]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "public_error",
    [
        # Sandbox stderr is the output of the user's own code.
        ReturnCodeError(SANDBOX_STDERR),
        KeyValueNodeError("Key-Value node 'persist #2' has no table selected."),
        EmptyKnowledgeQueryError(
            'Knowledge Retriever node "Search docs #1" got an empty query. '
            "Set a query, or map an input that has text."
        ),
    ],
    ids=["sandbox-stderr", "key-value", "empty-knowledge-query"],
)
async def test_public_error_is_shown_as_it_is_without_a_reference(public_error, captured_logs):
    error, details = await run_failing(RaisingNode(public_error))

    assert details == [str(public_error)]
    assert error.public_message == str(public_error)
    assert error.correlation_id is None
    assert captured_logs == []


@pytest.mark.asyncio
async def test_public_error_citing_a_reference_passes_that_reference_on(captured_logs):
    message = (
        'Knowledge Retriever node "Search docs #1" couldn\'t search its collection. '
        "Try again or contact your administrator (reference: 509c403ac7ac)."
    )

    error, details = await run_failing(
        RaisingNode(KnowledgeSearchError(message, correlation_id="509c403ac7ac"))
    )

    assert details == [message]
    assert error.public_message == message
    assert error.correlation_id == "509c403ac7ac"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "stop",
    [
        StopSession(status="stop"),
        StopSession(
            status="stop",
            reason="token budget exceeded",
            public_message="The flow stopped: it used up its token budget.",
        ),
        StopSession(
            status="expired", public_message="The flow stopped: it ran longer than allowed."
        ),
    ],
    ids=["manual-stop", "token-budget", "timeout"],
)
async def test_stop_session_is_reraised_unchanged_without_an_error_card(stop, captured_logs):
    error, details = await run_failing(RaisingNode(stop), expected_error=StopSession)

    assert error is stop
    assert details == []
    assert captured_logs == []


class FailingScheduleTriggerNode(ScheduleTriggerNode):
    async def execute(self, state, writer, execution_order, input_):
        raise RuntimeError(SECRET_TEXT)


@pytest.mark.asyncio
async def test_node_overriding_run_reports_failures_the_same_way(captured_logs):
    """Trigger nodes have their own run(); a failure there must not leak either."""
    node = FailingScheduleTriggerNode(session_id=7, node_name="schedule", stop_event=StopEvent())

    error, details = await run_failing(node)

    assert details == [error.public_message]
    assert re.fullmatch(GENERIC_DETAILS_PATTERN, error.public_message)
