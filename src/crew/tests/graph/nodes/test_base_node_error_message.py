import re

import pytest
from dotdict import DotDict
from loguru import logger

from services.graph.custom_message_writer import CustomSessionMessageWriter
from services.graph.events import StopEvent
from services.graph.exceptions import ReturnCodeError, StopSession
from services.graph.nodes.base_node import BaseNode

SECRET_TEXT = "postgres://admin:sup3rs3cret@internal-db.epicstaff.local:5432/crewdb"
GENERIC_DETAILS_PATTERN = r"^Node execution failed \(reference: [0-9a-f]{12}\)$"
SANDBOX_STDERR = "Traceback: NameError at /opt/crew/secret_path.py, token sk-live-abcdef"


class LeakyNode(BaseNode):
    TYPE = "LEAKY"

    async def execute(self, state, writer, execution_order, input_):
        raise RuntimeError(f"connection refused: {SECRET_TEXT}")


class SandboxFailingNode(BaseNode):
    TYPE = "PYTHON"

    async def execute(self, state, writer, execution_order, input_):
        raise ReturnCodeError(SANDBOX_STDERR)


class StoppedNode(BaseNode):
    TYPE = "PYTHON"

    async def execute(self, state, writer, execution_order, input_):
        raise StopSession(reason="manual stop")


def build_state():
    return {
        "variables": DotDict({}),
        "state_history": [],
        "system_variables": {},
    }


@pytest.fixture
def captured_logs():
    records: list[str] = []
    sink_id = logger.add(records.append, level="ERROR")
    yield records
    logger.remove(sink_id)


@pytest.mark.asyncio
async def test_failing_node_streams_generic_details_and_reraises(captured_logs):
    node = LeakyNode(session_id=7, node_name="leaky", stop_event=StopEvent())
    messages = []

    with pytest.raises(RuntimeError):
        await node.run(build_state(), writer=messages.append)

    error_messages = [
        message for message in messages if message.message_data.message_type == "error"
    ]
    assert len(error_messages) == 1
    details = error_messages[0].message_data.details

    assert re.match(GENERIC_DETAILS_PATTERN, details)
    assert SECRET_TEXT not in details
    assert "RuntimeError" not in details
    assert "connection refused" not in details


@pytest.mark.asyncio
async def test_raw_error_is_logged_with_the_streamed_correlation_id(captured_logs):
    node = LeakyNode(session_id=7, node_name="leaky", stop_event=StopEvent())
    messages = []

    with pytest.raises(RuntimeError):
        await node.run(build_state(), writer=messages.append)

    details = next(
        message.message_data.details
        for message in messages
        if message.message_data.message_type == "error"
    )
    correlation_id = re.search(r"reference: ([0-9a-f]{12})", details).group(1)

    matching_logs = [record for record in captured_logs if correlation_id in record]
    assert len(matching_logs) == 1
    assert SECRET_TEXT in matching_logs[0]
    assert "leaky" in matching_logs[0]
    assert "session_id=7" in matching_logs[0]


@pytest.mark.asyncio
async def test_each_failure_gets_its_own_correlation_id(captured_logs):
    node = LeakyNode(session_id=7, node_name="leaky", stop_event=StopEvent())
    details = []

    for _ in range(2):
        messages = []
        with pytest.raises(RuntimeError):
            await node.run(build_state(), writer=messages.append)
        details.extend(
            message.message_data.details
            for message in messages
            if message.message_data.message_type == "error"
        )

    assert details[0] != details[1]


def test_public_details_replace_the_generic_message_and_add_no_log_of_their_own(captured_logs):
    """When a caller supplies public_details, it already decided the error is an
    expected, routed outcome (not an unhandled fault) and logs it in its own
    words at whatever level fits — the chokepoint must not log a duplicate."""
    messages = []

    CustomSessionMessageWriter.add_error_message(
        session_id=7,
        node_name="leaky",
        writer=messages.append,
        error=RuntimeError(SECRET_TEXT),
        execution_order=0,
        public_details="Variable 'user_name' is not defined",
    )

    assert messages[0].message_data.details == "Variable 'user_name' is not defined"
    assert captured_logs == []


@pytest.mark.asyncio
async def test_sandbox_return_code_error_keeps_its_stderr_on_the_error_card(captured_logs):
    """ReturnCodeError only ever carries sandbox stderr (python_node.py,
    webhook_trigger_node.py), never agent/LLM-service text, so it bypasses the
    generic sanitization - same category the Decision Table nodes already
    forward unsanitized. A regression here previously replaced the stderr
    with the generic message."""
    node = SandboxFailingNode(session_id=7, node_name="pybad", stop_event=StopEvent())
    messages = []

    with pytest.raises(ReturnCodeError):
        await node.run(build_state(), writer=messages.append)

    error_messages = [
        message for message in messages if message.message_data.message_type == "error"
    ]
    assert len(error_messages) == 1
    assert error_messages[0].message_data.details == SANDBOX_STDERR
    assert captured_logs == []


@pytest.mark.asyncio
async def test_stop_session_gets_an_empty_error_card_not_the_generic_message(captured_logs):
    node = StoppedNode(session_id=7, node_name="stopped", stop_event=StopEvent())
    messages = []

    with pytest.raises(StopSession):
        await node.run(build_state(), writer=messages.append)

    error_messages = [
        message for message in messages if message.message_data.message_type == "error"
    ]
    assert len(error_messages) == 1
    assert error_messages[0].message_data.details == ""
    assert captured_logs == []


def test_error_passed_as_string_is_also_sanitized(captured_logs):
    messages = []

    CustomSessionMessageWriter.add_error_message(
        session_id=7,
        node_name="leaky",
        writer=messages.append,
        error=f"Error executing condition group 'group_a': {SECRET_TEXT}",
        execution_order=0,
    )

    details = messages[0].message_data.details
    assert re.match(GENERIC_DETAILS_PATTERN, details)
    assert SECRET_TEXT not in details
    assert SECRET_TEXT in captured_logs[0]
