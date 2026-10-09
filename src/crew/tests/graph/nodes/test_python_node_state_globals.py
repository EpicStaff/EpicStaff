import json
from unittest.mock import Mock

import pytest
from dotdict import DotDict

from services.graph.events import StopEvent
from services.graph.graph_builder import SessionGraphBuilder
from services.graph.nodes.python_node import PythonNode
from services.graph.nodes.webhook_trigger_node import WebhookTriggerNode
from services.redis_service import _encode
from src.shared.models import PythonCodeData

READS_STATE = "def main(**kw):\n    return state['variables']['a']"
IGNORES_STATE = "def main(**kw):\n    return 'x'"
STATE_GLOBALS = {"state": {"variables": {"a": 1}, "state_history": []}}


class CapturingExecutor:
    def __init__(self):
        self.additional_global_kwargs = None

    async def run_code(self, python_code_data, inputs, additional_global_kwargs=None, stop_event=None):
        self.additional_global_kwargs = additional_global_kwargs
        return {"returncode": 0, "stderr": "", "result_data": '"next"'}


def _state() -> dict:
    return {"variables": DotDict({"a": 1}), "state_history": [], "system_variables": {}, "execution_counts": {}}


def _code(code: str) -> PythonCodeData:
    return PythonCodeData(venv_name="default", code=code, entrypoint="main", libraries=[])


async def _run_python_node(code: str) -> dict:
    executor = CapturingExecutor()
    node = PythonNode(
        session_id=1,
        node_name="python",
        stop_event=StopEvent(),
        input_map={},
        output_variable_path=None,
        python_code_executor_service=executor,
        python_code_data=_code(code),
    )
    await node.execute(state=_state(), writer=lambda message: None, execution_order=1, input_={})
    return executor.additional_global_kwargs


async def _run_webhook_node(code: str) -> dict:
    executor = CapturingExecutor()
    node = WebhookTriggerNode(
        session_id=1,
        node_name="webhook",
        stop_event=StopEvent(),
        python_code_executor_service=executor,
        python_code_data=_code(code),
    )
    await node.execute(state=_state(), writer=lambda message: None, execution_order=1, input_={})
    return executor.additional_global_kwargs


async def _run_conditional_edge(code: str) -> dict:
    executor = CapturingExecutor()
    builder = SessionGraphBuilder(
        session_id=1,
        redis_service=Mock(),
        python_code_executor_service=executor,
        knowledge_search_service=Mock(),
        stop_event=StopEvent(),
    )
    builder._graph_builder = Mock()
    builder.add_conditional_edges("from", _code(code), input_map={"value": "variables.a"})
    decision_function = builder._graph_builder.add_conditional_edges.call_args.kwargs["path"]
    await decision_function(_state())
    sent = executor.additional_global_kwargs
    assert sent.pop("value") == 1
    return sent


@pytest.mark.asyncio
@pytest.mark.parametrize("run", [_run_python_node, _run_webhook_node, _run_conditional_edge])
@pytest.mark.parametrize(("code", "expected"), [(READS_STATE, STATE_GLOBALS), (IGNORES_STATE, {})], ids=["reads_state", "ignores_state"])
async def test_state_global_sent_only_when_code_reads_state(run, code, expected):
    assert await run(code) == expected


def test_encode_passes_str_through_and_json_encodes_dict():
    assert _encode('{"a": 1}') == '{"a": 1}'
    assert json.loads(_encode({"a": 1})) == {"a": 1}
