import pytest
from dotdict import DotDict
from loguru import logger

from services.graph.custom_message_writer import CustomSessionMessageWriter
from services.graph.events import StopEvent
from services.graph.exceptions import InvalidStatePathError, ReturnCodeError, StopSession
from services.graph.nodes.base_node import BaseNode
from services.graph.nodes.python_node import PythonNode
from src.shared.flow_templates import RefusedPlaceholderError, render_template
from src.shared.models import PythonCodeData
from tests.graph.test_graph_builder import FakePythonCodeExecutorService

SECRET_TEXT = "postgres://admin:secret-key-123@internal-db.epicstaff.local:5432/crewdb"
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


class RefusedPlaceholderNode(BaseNode):
    TYPE = "TASK"

    async def execute(self, state, writer, execution_order, input_):
        return render_template("Answer {context._x}", {"context": {"_x": SECRET_TEXT}})


class RecordingNode(BaseNode):
    TYPE = "PYTHON"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.executed = False

    async def execute(self, state, writer, execution_order, input_):
        self.executed = True
        return {"done": True}


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
async def test_failing_node_streams_the_node_failed_fact_and_reraises(captured_logs):
    node = LeakyNode(session_id=7, node_name="Save lead #3 #57", stop_event=StopEvent())
    messages = []

    with pytest.raises(RuntimeError):
        await node.run(build_state(), writer=messages.append)

    error_messages = [
        message for message in messages if message.message_data.message_type == "error"
    ]
    assert len(error_messages) == 1
    assert error_messages[0].message_data.details == 'Node "Save lead #3" failed.'


@pytest.mark.asyncio
async def test_raw_error_goes_to_the_log_with_session_and_node(captured_logs):
    node = LeakyNode(session_id=7, node_name="Save lead #3 #57", stop_event=StopEvent())
    messages = []

    with pytest.raises(RuntimeError):
        await node.run(build_state(), writer=messages.append)

    assert len(captured_logs) == 1
    assert SECRET_TEXT in captured_logs[0]
    assert "Save lead #3 #57" in captured_logs[0]
    assert "session_id=7" in captured_logs[0]
    assert "reference" not in captured_logs[0]


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
async def test_refused_template_placeholder_is_streamed_verbatim(captured_logs):
    node = RefusedPlaceholderNode(session_id=7, node_name="task", stop_event=StopEvent())
    messages = []

    with pytest.raises(RefusedPlaceholderError):
        await node.run(build_state(), writer=messages.append)

    error_messages = [
        message for message in messages if message.message_data.message_type == "error"
    ]
    assert len(error_messages) == 1
    assert error_messages[0].message_data.details == (
        "Placeholder '{context._x}' is not allowed: '_x' starts with '_'. "
        "Rename that variable or key."
    )
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


def test_error_passed_as_string_is_also_kept_out_of_the_stream(captured_logs):
    messages = []

    CustomSessionMessageWriter.add_error_message(
        session_id=7,
        node_name="Save lead #3 #57",
        writer=messages.append,
        error=f"Error executing condition group 'group_a': {SECRET_TEXT}",
        execution_order=0,
    )

    assert messages[0].message_data.details == 'Node "Save lead #3" failed.'
    assert SECRET_TEXT in captured_logs[0]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("input_map", "output_variable_path", "rejected_path"),
    [
        pytest.param(
            {"x": "variables.__class__.__init__.__globals__"},
            None,
            "variables.__class__.__init__.__globals__",
            id="input-map",
        ),
        pytest.param({}, "variables.__class__.status", "variables.__class__.status", id="output-path"),
    ],
)
async def test_underscore_state_path_fails_before_execute_with_a_public_message(
    captured_logs, input_map, output_variable_path, rejected_path
):
    node = RecordingNode(
        session_id=7,
        node_name="pathbad",
        stop_event=StopEvent(),
        input_map=input_map,
        output_variable_path=output_variable_path,
    )
    messages = []

    with pytest.raises(InvalidStatePathError):
        await node.run(build_state(), writer=messages.append)

    assert node.executed is False
    error_messages = [
        message for message in messages if message.message_data.message_type == "error"
    ]
    assert len(error_messages) == 1
    assert error_messages[0].message_data.details == (
        f"Variable path '{rejected_path}' is not allowed: path segments cannot start with '_'."
    )
    assert captured_logs == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("output_variable_path", "variables", "expected"),
    [
        (
            "variables.tags[5]",
            {"tags": ["x"]},
            'Output path "variables.tags[5]" of Python node "Clean data #2" doesn\'t exist.',
        ),
        (
            "variables.name.first",
            {"name": "Ann"},
            'Output path "variables.name.first" of Python node "Clean data #2" doesn\'t exist.',
        ),
    ],
    ids=["index-out-of-range", "name-on-a-string"],
)
async def test_output_path_that_does_not_exist_streams_the_fact(
    captured_logs, output_variable_path, variables, expected
):
    node = PythonNode(
        session_id=7,
        node_name="Clean data #2 #41",
        stop_event=StopEvent(),
        input_map={},
        output_variable_path=output_variable_path,
        python_code_executor_service=FakePythonCodeExecutorService(),
        python_code_data=PythonCodeData(code="def main():\n    return 1\n", entrypoint="main"),
    )
    state = build_state()
    state["variables"] = DotDict(variables)
    messages = []

    with pytest.raises(InvalidStatePathError):
        await node.run(state, writer=messages.append)

    error_messages = [
        message
        for message in messages
        if getattr(message.message_data, "message_type", None) == "error"
    ]
    assert [message.message_data.details for message in error_messages] == [expected]


@pytest.mark.asyncio
@pytest.mark.parametrize("mapped_path", ["", "|null", "|fallback"])
async def test_input_map_entry_without_a_path_fails_before_execute_with_a_public_message(
    captured_logs, mapped_path
):
    node = RecordingNode(
        session_id=7,
        node_name="nopath",
        stop_event=StopEvent(),
        input_map={"user": mapped_path},
    )
    messages = []

    with pytest.raises(InvalidStatePathError):
        await node.run(build_state(), writer=messages.append)

    assert node.executed is False
    error_details = [
        message.message_data.details
        for message in messages
        if message.message_data.message_type == "error"
    ]
    assert error_details == ["Input map entry 'user' has no variable path."]
    assert captured_logs == []
