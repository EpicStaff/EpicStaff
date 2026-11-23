"""A failed code run raises, and streams, the text the user should see.

The code's own failure is its stderr. A failure of the sandbox itself arrives as the
result's `error` `{code, detail}`; its `detail` is shown after whatever the code wrote to
stderr. An `error` that isn't a valid `{code, detail}` is never shown: the generic
server-error text stands in for it. The streamed python message carries that same text
as `stderr` and no `error`, the shape the running-graph UI reads.
"""

import pytest

from models.graph_models import PythonMessageData
from services.graph.events import StopEvent
from services.graph.exceptions import ReturnCodeError
from services.graph.nodes.python_node import PythonNode
from services.graph.nodes.webhook_trigger_node import WebhookTriggerNode
from src.shared.models import PythonCodeData

USER_TRACEBACK = "Traceback (most recent call last):\nNameError: name 'x' is not defined"
SANDBOX_LOST = "Sandbox worker was lost; the job may not have finished."


class FixedResultExecutor:
    def __init__(self, result: dict):
        self._result = result

    async def run_code(
        self,
        python_code_data,
        inputs,
        additional_global_kwargs=None,
        stop_event=None,
        storage_credentials=None,
    ):
        return dict(self._result)


def _state() -> dict:
    return {"variables": {}, "state_history": [], "system_variables": {}, "execution_counts": {}}


def _python_node(executor) -> PythonNode:
    return PythonNode(
        session_id=1,
        node_name="python",
        stop_event=StopEvent(),
        input_map={},
        output_variable_path=None,
        python_code_executor_service=executor,
        python_code_data=PythonCodeData(code="def main(): pass", entrypoint="main"),
    )


def _webhook_node(executor) -> WebhookTriggerNode:
    return WebhookTriggerNode(
        session_id=1,
        node_name="webhook",
        stop_event=StopEvent(),
        python_code_executor_service=executor,
        python_code_data=PythonCodeData(code="def main(): pass", entrypoint="main"),
    )


def _failed(stderr: str, error) -> dict:
    return {
        "execution_id": "exec-1",
        "returncode": 1,
        "result_data": None,
        "stdout": "",
        "stderr": stderr,
        "error": error,
    }


FAILED_RUNS = [
    pytest.param(_failed(USER_TRACEBACK, None), USER_TRACEBACK, id="code-failed"),
    pytest.param(
        _failed("", {"code": "worker_lost", "detail": SANDBOX_LOST}),
        SANDBOX_LOST,
        id="sandbox-failed",
    ),
    pytest.param(
        _failed(
            "child wrote this",
            {"code": "result_too_large", "detail": "The function's return value is too big to save."},
        ),
        "child wrote this\nThe function's return value is too big to save.",
        id="code-wrote-then-sandbox-failed",
    ),
    pytest.param(
        _failed("", {"code": "worker_lost", "detail": SANDBOX_LOST, "attr": None}),
        SANDBOX_LOST,
        id="error-with-an-extra-field",
    ),
    pytest.param(
        _failed("", {"code": "worker_lost", "reason": "/opt/sandbox/worker.py line 3"}),
        "The code couldn't run because of a server error.",
        id="malformed-error",
    ),
]


async def _run(build_node, result: dict) -> tuple[ReturnCodeError, list]:
    streamed = []
    node = build_node(FixedResultExecutor(result))
    with pytest.raises(ReturnCodeError) as raised:
        await node.execute(state=_state(), writer=streamed.append, execution_order=1, input_={})
    return raised.value, streamed


@pytest.mark.asyncio
@pytest.mark.parametrize("build_node", [_python_node, _webhook_node], ids=["python", "webhook"])
@pytest.mark.parametrize(("result", "expected"), FAILED_RUNS)
async def test_a_failed_run_raises_the_text_meant_for_the_user(build_node, result, expected):
    raised, _ = await _run(build_node, result)

    assert str(raised) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("build_node", [_python_node, _webhook_node], ids=["python", "webhook"])
@pytest.mark.parametrize(("result", "expected"), FAILED_RUNS)
async def test_a_failed_run_streams_the_shown_text_as_stderr_without_an_error(
    build_node, result, expected
):
    _, streamed = await _run(build_node, result)

    [execution_data] = [
        message.message_data.python_code_execution_data
        for message in streamed
        if isinstance(message.message_data, PythonMessageData)
    ]
    assert "error" not in execution_data
    assert execution_data["stderr"] == expected
