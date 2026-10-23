"""Tests for DecisionTableNodeSubgraph error reporting.

The sandbox is replaced with a stub RunPythonCodeService, so the subgraph's own
condition/manipulation handling is exercised without a real venv.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from dotdict import DotDict
from langgraph.graph import StateGraph

from models.state import State
from services.graph.events import StopEvent

from src.crew.services.graph.subgraphs.decision_table_node import (
    DecisionTableNodeSubgraph,
)
from src.shared.models import ConditionGroupData, DecisionTableNodeData


SANDBOX_STDERR = "Traceback: NameError at /opt/crew/secret_path.py, token sk-live-abcdef"


class StubRunPythonCodeService:
    """Return a fixed sandbox result for every run_code call."""

    def __init__(self, returncode: int, result_data: str = "null", stderr: str = ""):
        self._result = {
            "returncode": returncode,
            "result_data": result_data,
            "stderr": stderr,
            "execution_id": "test",
        }

    async def run_code(self, python_code_data, inputs, stop_event=None, storage_credentials=None):
        return dict(self._result)


def make_state(variables: dict | None = None) -> State:
    return {
        "state_history": [],
        "variables": DotDict(variables or {}),
        "system_variables": {"nodes": {}, "execution_order": 0},
        "execution_counts": {},
    }


def build_subgraph(node_data: DecisionTableNodeData, run_code_service):
    redis_service = MagicMock()
    redis_service.aadd_graph_message = AsyncMock()
    subgraph = DecisionTableNodeSubgraph(
        session_id=1,
        decision_table_node_data=node_data,
        graph_builder=StateGraph(State),
        stop_event=StopEvent(),
        run_code_execution_service=run_code_service,
        redis_service=redis_service,
    ).build()
    return subgraph, redis_service


def published_messages(redis_service: MagicMock) -> list[dict]:
    return [
        json.loads(added.args[1])["message_data"]
        for added in redis_service.aadd_graph_message.await_args_list
    ]


def complex_group(group_name: str, expression: str, next_node: str) -> ConditionGroupData:
    return ConditionGroupData(
        group_name=group_name,
        group_type="complex",
        expression=expression,
        next_node=next_node,
    )


@pytest.mark.asyncio
async def test_matching_condition_group_routes_to_its_next_node():
    node_data = DecisionTableNodeData(
        node_name="dt_node",
        conditional_group_list=[complex_group("hit", "True", "node_A")],
        default_next_node="fallback",
    )
    subgraph, _ = build_subgraph(node_data, StubRunPythonCodeService(0, result_data="true"))

    result = await subgraph.ainvoke(make_state())

    assert result["system_variables"]["nodes"]["dt_node"]["result_node"] == "node_A"


@pytest.mark.asyncio
async def test_failing_condition_group_keeps_its_composed_message_for_the_client():
    """The composed domain text reaches the client through public_details; the
    sanitization of the raw exception must not replace it with a generic message."""
    node_data = DecisionTableNodeData(
        node_name="dt_node",
        conditional_group_list=[complex_group("broken", "undefined_name", "node_A")],
        next_error_node="error_node",
    )
    subgraph, redis_service = build_subgraph(
        node_data, StubRunPythonCodeService(1, stderr=SANDBOX_STDERR)
    )

    result = await subgraph.ainvoke(make_state())

    assert result["system_variables"]["nodes"]["dt_node"]["result_node"] == "error_node"
    error_message = next(
        message
        for message in published_messages(redis_service)
        if message["message_type"] == "error"
    )
    assert error_message["details"] == (
        "Error executing condition group 'broken': "
        f"Expression execution failed with error: {SANDBOX_STDERR}"
    )
