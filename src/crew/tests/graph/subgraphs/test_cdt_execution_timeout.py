"""The classification decision table node applies its execution timeout to every
sandbox run and routes a timeout through its error path.

Invariant: pre-computation, each row-expression batch, each manipulation and
post-computation each ask the sandbox for the node's full timeout (minutes * 60).
When the sandbox kills one of them, the node routes to its error node with a
message naming the limit in minutes, not the sandbox's raw stderr.

`RunPythonCodeService.run_code` is patched; the subgraph runs for real.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from dotdict import DotDict
from langgraph.graph import StateGraph

from models.state import State
from services.graph.events import StopEvent
from src.crew.services.graph.subgraphs.classification_decision_table_node import (
    ClassificationDecisionTableNodeSubgraph,
)
from src.crew.services.run_python_code_service import RunPythonCodeService
from src.crew.utils.singleton_meta import SingletonMeta
from src.shared.models import PythonCodeData
from src.shared.models.graph_nodes import (
    ClassificationConditionGroupData,
    ClassificationDecisionTableNodeData,
)

TIMEOUT_MESSAGE = "Python code exceeded the execution timeout of 2 min and was terminated."


@pytest.fixture(autouse=True)
def reset_singleton():
    SingletonMeta._instances.pop(RunPythonCodeService, None)
    yield
    SingletonMeta._instances.pop(RunPythonCodeService, None)


def _code(body: str) -> PythonCodeData:
    return PythonCodeData(
        venv_name="default", code=f"def main(**kwargs):\n    {body}", entrypoint="main", libraries=[]
    )


def _state() -> State:
    return {
        "state_history": [],
        "variables": DotDict({}),
        "system_variables": {
            "nodes": {"cdt_node": {"result_node": None, "default_node": None, "execution_order": 0}},
            "execution_order": 0,
        },
        "execution_counts": {},
    }


def _run_subgraph(node_data: ClassificationDecisionTableNodeData):
    redis_service = MagicMock()
    subgraph = ClassificationDecisionTableNodeSubgraph(
        session_id=1,
        node_data=node_data,
        graph_builder=StateGraph(State),
        stop_event=StopEvent(),
        redis_service=redis_service,
    ).build()
    return redis_service, subgraph


def _published_messages(redis_service: MagicMock) -> list[dict]:
    return [
        json.loads(added.args[1])["message_data"]
        for added in redis_service.add_graph_message.call_args_list
    ]


def _patch_run_code(monkeypatch, result_for) -> list[float | None]:
    """Patch run_code to answer with `result_for(inputs)`; return the timeouts asked for."""
    timeouts: list[float | None] = []

    async def fake_run_code(
        self,
        python_code_data,
        inputs,
        stop_event=None,
        additional_global_kwargs=None,
        storage_credentials=None,
        timeout=None,
    ):
        timeouts.append(timeout)
        return result_for(inputs)

    monkeypatch.setattr(RunPythonCodeService, "run_code", fake_run_code, raising=True)
    return timeouts


def _succeed(inputs: dict) -> dict:
    if "expressions" in inputs:
        result = {"results": [True], "error": None}
    else:
        result = inputs.get("variables", {})
    return {"returncode": 0, "result_data": json.dumps(result), "stderr": "", "execution_id": "x"}


def _time_out(inputs: dict) -> dict:
    return {
        "returncode": 124,
        "result_data": None,
        "stderr": "Execution exceeded 120 seconds and was terminated.",
        "execution_id": "x",
        "timed_out": True,
        "effective_timeout_seconds": 120.0,
    }


@pytest.mark.asyncio
async def test_every_sandbox_run_of_the_node_gets_the_node_timeout(monkeypatch):
    timeouts = _patch_run_code(monkeypatch, _succeed)
    node_data = ClassificationDecisionTableNodeData(
        node_name="cdt_node",
        pre_python_code=_code("return {}"),
        post_python_code=_code("return {}"),
        condition_groups=[
            ClassificationConditionGroupData(
                group_name="row",
                order=0,
                expression="True",
                manipulation="variables.ran = True",
                next_node="next",
            )
        ],
        execution_timeout=3,
    )
    _, subgraph = _run_subgraph(node_data)

    await subgraph.ainvoke(_state())

    # pre, the expression batch, the manipulation and post.
    assert timeouts == [180, 180, 180, 180]


@pytest.mark.asyncio
async def test_schema_without_a_timeout_lets_the_sandbox_apply_its_ceiling(monkeypatch):
    timeouts = _patch_run_code(monkeypatch, _succeed)
    node_data = ClassificationDecisionTableNodeData(
        node_name="cdt_node",
        condition_groups=[
            ClassificationConditionGroupData(
                group_name="row", order=0, expression="True", next_node="next"
            )
        ],
    )
    _, subgraph = _run_subgraph(node_data)

    await subgraph.ainvoke(_state())

    assert timeouts == [None]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("node_overrides", "expected_details"),
    [
        (
            {"pre_python_code": _code("return {}")},
            f"Pre-computation execution failed: {TIMEOUT_MESSAGE}",
        ),
        (
            {"post_python_code": _code("return {}")},
            f"Post-computation execution failed: {TIMEOUT_MESSAGE}",
        ),
        (
            {"expression": "True"},
            f"Error in condition 'row': Expression execution failed: {TIMEOUT_MESSAGE}",
        ),
        (
            {"manipulation": "variables.ran = True"},
            f"Manipulation execution failed: {TIMEOUT_MESSAGE}",
        ),
    ],
    ids=["pre-computation", "post-computation", "expression", "manipulation"],
)
async def test_timed_out_run_routes_to_the_error_node_naming_the_limit(
    monkeypatch, node_overrides, expected_details
):
    _patch_run_code(monkeypatch, _time_out)
    group_fields = {
        key: node_overrides.pop(key) for key in ("expression", "manipulation") if key in node_overrides
    }
    node_data = ClassificationDecisionTableNodeData(
        node_name="cdt_node",
        condition_groups=[
            ClassificationConditionGroupData(
                group_name="row", order=0, next_node="next", **group_fields
            )
        ],
        next_error_node="error_node",
        execution_timeout=2,
        **node_overrides,
    )
    redis_service, subgraph = _run_subgraph(node_data)

    result = await subgraph.ainvoke(_state())

    assert result["system_variables"]["nodes"]["cdt_node"]["result_node"] == "error_node"
    [error_message] = [
        message
        for message in _published_messages(redis_service)
        if message["message_type"] == "error"
    ]
    assert expected_details in error_message["details"]
    assert "Execution exceeded 120 seconds" not in error_message["details"]
