"""Code-running nodes ask the sandbox for their own execution timeout and report a
run it killed as a timeout.

Invariant: a node configured with N minutes sends `timeout=N*60` seconds with every
sandbox run (None when the schema predates the field, so the sandbox applies its
ceiling). When the sandbox reports `timed_out`, the node fails with
`PythonCodeTimeoutError` naming the limit the sandbox actually applied, in minutes,
instead of a generic `ReturnCodeError` carrying the raw stderr. Any other non-zero
exit stays a plain `ReturnCodeError`.

The sandbox is replaced by `RecordingExecutor`; the node classes and the graph
builder run for real.
"""

import asyncio
from unittest.mock import Mock

import pytest
from dotdict import DotDict

from services.graph.events import StopEvent
from services.graph.exceptions import (
    PythonCodeTimeoutError,
    ReturnCodeError,
    timeout_message,
)
from services.graph.graph_session_manager_service import (
    KnowledgeSearchService,
    RedisService,
    SessionGraphBuilder,
)
from services.graph.nodes.audio_transcription_node import AudioTranscriptionNode
from services.graph.nodes.file_extractor_node import FileContentExtractorNode
from services.graph.nodes.python_node import PythonNode
from services.graph.nodes.webhook_trigger_node import WebhookTriggerNode
from src.shared.models import (
    AudioTranscriptionNodeData,
    EdgeData,
    FileExtractorNodeData,
    GraphData,
    PythonCodeData,
    PythonNodeData,
    SessionData,
    WebhookTriggerNodeData,
)

SUCCESS = {"returncode": 0, "stderr": "", "result_data": '"done"', "execution_id": "run"}
TIMED_OUT = {
    "returncode": 124,
    "stderr": "Execution exceeded 120 seconds and was terminated.",
    "result_data": None,
    "execution_id": "run",
    "timed_out": True,
    "effective_timeout_seconds": 120.0,
}
CRASHED = {
    "returncode": 1,
    "stderr": "ZeroDivisionError: division by zero",
    "result_data": None,
    "execution_id": "run",
    "timed_out": False,
    "effective_timeout_seconds": None,
}
FILE_INPUT_MAP = {"file": "variables.file"}


class RecordingExecutor:
    """Stands in for RunPythonCodeService: records each requested timeout and
    answers with a fixed sandbox result."""

    def __init__(self, result: dict):
        self.result = result
        self.timeouts: list[float | None] = []

    async def run_code(
        self,
        python_code_data,
        inputs,
        additional_global_kwargs=None,
        stop_event=None,
        storage_credentials=None,
        timeout=None,
    ):
        self.timeouts.append(timeout)
        return dict(self.result)


def _code() -> PythonCodeData:
    return PythonCodeData(
        venv_name="default", code="def main(**kw):\n    return 'x'", entrypoint="main", libraries=[]
    )


def _python_node(executor, execution_timeout):
    return PythonNode(
        session_id=1,
        node_name="python",
        stop_event=StopEvent(),
        input_map={},
        output_variable_path=None,
        python_code_executor_service=executor,
        python_code_data=_code(),
        execution_timeout=execution_timeout,
    )


def _webhook_trigger_node(executor, execution_timeout):
    return WebhookTriggerNode(
        session_id=1,
        node_name="webhook",
        stop_event=StopEvent(),
        python_code_executor_service=executor,
        python_code_data=_code(),
        execution_timeout=execution_timeout,
    )


def _file_extractor_node(executor, execution_timeout):
    return FileContentExtractorNode(
        session_id=1,
        node_name="file_extractor",
        stop_event=StopEvent(),
        input_map=FILE_INPUT_MAP,
        output_variable_path=None,
        python_code_executor_service=executor,
        execution_timeout=execution_timeout,
    )


def _audio_transcription_node(executor, execution_timeout):
    return AudioTranscriptionNode(
        session_id=1,
        node_name="audio_transcription",
        stop_event=StopEvent(),
        input_map=FILE_INPUT_MAP,
        output_variable_path=None,
        python_code_executor_service=executor,
        execution_timeout=execution_timeout,
    )


NODE_FACTORIES = [
    pytest.param(_python_node, id="python"),
    pytest.param(_webhook_trigger_node, id="webhook-trigger"),
    pytest.param(_file_extractor_node, id="file-extractor"),
    pytest.param(_audio_transcription_node, id="audio-transcription"),
]


def _state() -> dict:
    return {
        "variables": DotDict({"file": "org_1/report.pdf"}),
        "state_history": [],
        "system_variables": {},
        "execution_counts": {},
    }


async def _execute(node) -> object:
    return await node.execute(
        state=_state(), writer=lambda message: None, execution_order=1, input_={}
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("make_node", NODE_FACTORIES)
@pytest.mark.parametrize(
    ("execution_timeout", "expected_seconds"),
    [(3, 180), (1, 60), (None, None)],
    ids=["three-minutes", "one-minute", "schema-without-timeout"],
)
async def test_node_sends_its_timeout_in_seconds(make_node, execution_timeout, expected_seconds):
    executor = RecordingExecutor(SUCCESS)

    await _execute(make_node(executor, execution_timeout))

    assert executor.timeouts == [expected_seconds]


@pytest.mark.asyncio
@pytest.mark.parametrize("make_node", NODE_FACTORIES)
async def test_timed_out_run_raises_a_timeout_error_naming_the_applied_limit(make_node):
    node = make_node(RecordingExecutor(TIMED_OUT), 5)

    with pytest.raises(PythonCodeTimeoutError) as raised:
        await _execute(node)

    assert raised.value.timeout_seconds == 120.0
    assert str(raised.value) == (
        "Python code exceeded the execution timeout of 2 min and was terminated."
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("make_node", NODE_FACTORIES)
async def test_other_failure_stays_a_plain_return_code_error(make_node):
    node = make_node(RecordingExecutor(CRASHED), 5)

    with pytest.raises(ReturnCodeError) as raised:
        await _execute(node)

    assert not isinstance(raised.value, PythonCodeTimeoutError)
    assert str(raised.value) == CRASHED["stderr"]


@pytest.mark.parametrize(
    ("effective_timeout_seconds", "expected"),
    [
        (300.0, "Python code exceeded the execution timeout of 5 min and was terminated."),
        (90.0, "Python code exceeded the execution timeout of 1.5 min and was terminated."),
        (None, "Python code exceeded the execution timeout and was terminated."),
    ],
    ids=["whole-minutes", "fraction-of-a-minute", "limit-not-reported"],
)
def test_timeout_message(effective_timeout_seconds, expected):
    assert timeout_message(effective_timeout_seconds) == expected
    assert str(PythonCodeTimeoutError(effective_timeout_seconds)) == expected


def _graph_data_with(node_name: str, **node_lists) -> GraphData:
    return GraphData(
        name="timeout-graph",
        edge_list=[EdgeData(start_key="__start__", end_key=node_name)],
        entrypoint=node_name,
        end_node=None,
        **node_lists,
    )


SCHEMA_CASES = [
    pytest.param(
        "python",
        {
            "python_node_list": [
                PythonNodeData(
                    node_name="python", python_code=_code(), input_map={}, execution_timeout=4
                )
            ]
        },
        id="python",
    ),
    pytest.param(
        "webhook",
        {
            "webhook_trigger_node_data_list": [
                WebhookTriggerNodeData(node_name="webhook", python_code=_code(), execution_timeout=4)
            ]
        },
        id="webhook-trigger",
    ),
    pytest.param(
        "file_extractor",
        {
            "file_extractor_node_list": [
                FileExtractorNodeData(
                    node_name="file_extractor", input_map=FILE_INPUT_MAP, execution_timeout=4
                )
            ]
        },
        id="file-extractor",
    ),
    pytest.param(
        "audio_transcription",
        {
            "audio_transcription_node_list": [
                AudioTranscriptionNodeData(
                    node_name="audio_transcription",
                    input_map=FILE_INPUT_MAP,
                    execution_timeout=4,
                )
            ]
        },
        id="audio-transcription",
    ),
]


@pytest.mark.parametrize(("node_name", "node_lists"), SCHEMA_CASES)
def test_compiled_graph_runs_the_node_with_the_schema_timeout(node_name, node_lists):
    executor = RecordingExecutor(SUCCESS)
    redis_service = RedisService(
        host="127.0.0.1", port=6379, user="default", password="redis_password"
    )
    redis_service.add_graph_message = Mock()
    builder = SessionGraphBuilder(
        session_id=1,
        redis_service=redis_service,
        python_code_executor_service=executor,
        knowledge_search_service=Mock(spec=KnowledgeSearchService),
        stop_event=StopEvent(),
    )
    compiled_graph = builder.compile_from_schema(
        SessionData(
            id=1, org_id=1, initial_state={}, graph=_graph_data_with(node_name, **node_lists)
        )
    )

    async def run_graph():
        async for _ in compiled_graph.astream(
            {
                "state_history": [],
                "variables": DotDict({"file": "org_1/report.pdf"}),
                "system_variables": {},
            },
            stream_mode=["values"],
        ):
            pass

    asyncio.run(run_graph())

    assert executor.timeouts == [240]
