"""SubGraphNode: runs a child flow on mapped input and writes its variables back.

Every test runs a real compiled child graph through `SubGraphNode.run()`; Python
nodes execute in-process through FakePythonCodeExecutorService.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from dotdict import DotDict
from langgraph.graph import StateGraph
from litellm.types.utils import ModelResponse, Usage
from loguru import logger

from models.state import State
from services.graph.events import StopEvent
from services.graph.exceptions import InvalidStatePathError, ReturnCodeError, StopSession
from services.graph.graph_builder import SessionGraphBuilder
from services.graph.subgraphs.subgraph_node import SubGraphNode
from src.shared.models import (
    EdgeData,
    GraphData,
    KeyValueNodeData,
    PythonCodeData,
    PythonNodeData,
    SubGraphData,
)
from src.shared.models.ai_providers import LLMConfigData, LLMData
from src.shared.models.graph_nodes import (
    ClassificationConditionGroupData,
    ClassificationDecisionTableNodeData,
    PromptConfigData,
    SubGraphNodeData,
)
from tests.graph.test_graph_builder import FakePythonCodeExecutorService
from tests.secrets_cryptographer import TEST_SECRETS_CRYPTOGRAPHER

pytestmark = pytest.mark.asyncio

CHILD_OUTPUT = {"a": {"b": "sub"}, "new_var": 42}


def _python_child(code: str, input_map: dict | None = None) -> GraphData:
    return GraphData(
        name="child",
        entrypoint="produce",
        end_node=None,
        python_node_list=[
            PythonNodeData(
                node_name="produce",
                python_code=PythonCodeData(
                    code=code, entrypoint="main", global_kwargs={}
                ),
                input_map=input_map or {},
                output_variable_path="variables",
            )
        ],
        edge_list=[EdgeData(start_key="produce", end_key="__end__")],
    )


def _subgraph_node(
    child: GraphData, output_variable_path: str, input_map=None, audit_retention_days=0, **services
) -> SubGraphNode:
    parent_builder = SimpleNamespace(
        **{
            "redis_service": None,
            "python_code_executor_service": FakePythonCodeExecutorService(),
            "knowledge_search_service": None,
            "agent_task_service": None,
            "key_value_client": None,
            "secrets_cryptographer": None,
            **services,
        }
    )
    return SubGraphNode(
        session_id=1,
        subgraph_node_data=SubGraphNodeData(
            node_name="sub_node",
            subgraph_id=7,
            input_map=input_map or {},
            output_variable_path=output_variable_path,
        ),
        unique_subgraph_list=[SubGraphData(id=7, data=child)],
        graph_builder=StateGraph(State),
        org_id=1,
        audit_retention_days=audit_retention_days,
        session_graph_builder=parent_builder,
        stop_event=StopEvent(),
    )


def _parent_state() -> dict:
    return {
        "variables": DotDict(
            {
                "a": {"b": "parent_value", "keep": "untouched"},
                "records": [{"name": "first"}, {"name": "second"}],
                "scalar": 1,
            }
        ),
        "state_history": [],
        "system_variables": {},
        "execution_counts": {},
    }


PARENT = {"a": {"b": "parent_value", "keep": "untouched"}, "records": [{"name": "first"}, {"name": "second"}], "scalar": 1}


@pytest.mark.parametrize(
    ("output_variable_path", "expected_variables"),
    [
        pytest.param(
            "variables.new_key", {**PARENT, "new_key": CHILD_OUTPUT}, id="new-key",
        ),
        pytest.param(
            "variables.a.b",
            {**PARENT, "a": {"b": CHILD_OUTPUT, "keep": "untouched"}},
            id="nested-path-replaced",
        ),
        pytest.param(
            # An existing object at the path is merged into, not replaced.
            "variables.a",
            {**PARENT, "a": {"b": "parent_value", "keep": "untouched", **CHILD_OUTPUT}},
            id="existing-object-merged",
        ),
        pytest.param(
            # Like a Python node: deep-merged into the parent, parent-only keys kept.
            "variables",
            {**PARENT, "a": {"b": "sub", "keep": "untouched"}, "new_var": 42},
            id="whole-variables-deep-merged",
        ),
    ],
)
async def test_child_variables_are_written_back_at_the_output_path(output_variable_path, expected_variables):
    node = _subgraph_node(_python_child(f"def main(): return {CHILD_OUTPUT!r}"), output_variable_path)
    state = _parent_state()

    updated = await node.run(state, writer=lambda message: None)

    assert updated["variables"].deep_dump() == expected_variables
    # The parent's own state is never mutated in place.
    assert state["variables"].deep_dump() == PARENT


@pytest.mark.parametrize("output_variable_path", ["variables", "variables.a", "variables.new_key"])
async def test_returned_variables_share_nothing_with_parent_state_or_history(output_variable_path):
    node = _subgraph_node(_python_child(f"def main(): return {CHILD_OUTPUT!r}"), output_variable_path)
    state = _parent_state()
    updated = await node.run(state, writer=lambda message: None)
    (history_item,) = updated["state_history"]
    history_before = DotDict(history_item["output"]).deep_dump()

    variables = updated["variables"]
    variables.a.b = "mutated"
    variables.records[0].name = "mutated"
    variables.records.append({"name": "third"})
    written = variables if output_variable_path == "variables" else variables[output_variable_path.split(".")[1]]
    written.a = {"b": "mutated"}

    assert state["variables"].deep_dump() == PARENT
    assert DotDict(history_item["output"]).deep_dump() == history_before
    # A history item travels with every later message; a variables snapshot would grow without bound.
    assert "variables" not in history_item


async def test_child_messages_are_tagged_with_the_subgraph_run():
    node = _subgraph_node(_python_child("def main(): return {'done': True}"), "variables.result")
    messages = []

    await node.run(_parent_state(), writer=messages.append)

    start, *inner, finish = messages
    run_id = start.message_data.subgraph_execution_id
    assert inner, "the child node's own messages must be forwarded"
    assert all(message.message_data["subgraph_execution_ids"] == [run_id] for message in inner)


async def test_start_and_finish_payloads_carry_the_subgraph_node_type():
    node = _subgraph_node(_python_child("def main(): return {'done': True}"), "variables.result")
    messages = []

    await node.run(_parent_state(), writer=messages.append)

    start, *inner, finish = messages
    assert start.to_payload()["node_type"] == "SUBGRAPH"
    assert finish.to_payload()["node_type"] == "SUBGRAPH"
    # The child's own rows keep the child node's type, not the wrapping subflow's.
    assert {message.to_payload()["node_type"] for message in inner} - {""} == {"PYTHON"}


async def test_compiled_child_is_reused_across_runs_with_fresh_state(monkeypatch):
    node = _subgraph_node(
        _python_child("def main(x): return {'doubled': x * 2}", input_map={"x": "variables.x"}),
        "variables.result",
        input_map={"x": "variables.x"},
    )
    compile_calls = []
    real_compile = SessionGraphBuilder.compile_from_schema

    def counting_compile(builder, session_data):
        compile_calls.append(session_data)
        return real_compile(builder, session_data)

    monkeypatch.setattr(SessionGraphBuilder, "compile_from_schema", counting_compile)
    state = _parent_state()
    state["variables"].x = 2

    first = await node.run(state, writer=lambda message: None)
    first["variables"].x = 5
    second = await node.run(first, writer=lambda message: None)

    assert len(compile_calls) == 1
    assert second["variables"].result.doubled == 10
    assert [item["output"]["doubled"] for item in second["state_history"]] == [4, 10]


async def test_child_flow_is_built_with_the_parents_audit_retention(monkeypatch):
    node = _subgraph_node(
        _python_child("def main(): return {'done': True}"), "variables.result", audit_retention_days=90
    )
    compiled_session_data = []
    real_compile = SessionGraphBuilder.compile_from_schema

    def recording_compile(builder, session_data):
        compiled_session_data.append(session_data)
        return real_compile(builder, session_data)

    monkeypatch.setattr(SessionGraphBuilder, "compile_from_schema", recording_compile)

    await node.run(_parent_state(), writer=lambda message: None)

    assert [session_data.audit_retention_days for session_data in compiled_session_data] == [90]


class FakeKeyValueClient:
    async def read(self, session_id, table_id, keys):
        return {"values": {key: f"stored {key}" for key in keys}, "table_name": "Customers"}


async def test_child_nodes_use_the_parents_services():
    """A child flow with a Key-Value node only runs if the parent's client is passed down."""
    child = GraphData(
        name="child",
        entrypoint="persist_1",
        end_node=None,
        key_value_node_list=[
            KeyValueNodeData(
                node_name="persist_1", key_value_table_id=3, mode="read",
                entries=[{"key": "k", "value": "variables.out"}], input_map={},
            )
        ],
        edge_list=[EdgeData(start_key="persist_1", end_key="__end__")],
    )
    node = _subgraph_node(child, "variables.result", key_value_client=FakeKeyValueClient())

    updated = await node.run(_parent_state(), writer=lambda message: None)

    assert updated["variables"].result.out == "stored k"


def _error_details(messages) -> list[str]:
    return [
        message.message_data.details
        for message in messages
        if getattr(message.message_data, "message_type", None) == "error"
    ]


async def test_child_classification_table_decrypts_with_the_parents_cryptographer():
    """A CDT prompt in a child flow reaches its LLM with the plaintext key only if the
    parent's cryptographer is passed down."""
    child = GraphData(
        name="child",
        entrypoint="classify_1",
        end_node=None,
        classification_decision_table_node_list=[
            ClassificationDecisionTableNodeData(
                node_name="classify_1",
                condition_groups=[
                    ClassificationConditionGroupData(
                        group_name="row0", order=0, prompt_id="classify", next_node="__end__"
                    )
                ],
                prompts={
                    "classify": PromptConfigData(
                        prompt_text="Classify",
                        llm_data=LLMData(
                            provider="openai",
                            config=LLMConfigData(
                                model="gpt-4o-mini",
                                api_key=TEST_SECRETS_CRYPTOGRAPHER.encrypt("sk-plain"),
                            ),
                        ),
                        result_variable="label",
                    )
                },
            )
        ],
    )
    node = _subgraph_node(
        child, "variables.result", secrets_cryptographer=TEST_SECRETS_CRYPTOGRAPHER
    )
    reply = ModelResponse(
        model="gpt-4o-mini",
        choices=[{"message": {"role": "assistant", "content": '{"label": "x"}'}}],
        usage=Usage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
    )

    with patch("litellm.acompletion", new_callable=AsyncMock, return_value=reply) as completion:
        await node.run(_parent_state(), writer=lambda message: None)

    assert completion.call_args.kwargs["api_key"] == "sk-plain"


async def test_underscore_output_path_fails_before_the_child_flow_runs():
    node = _subgraph_node(_python_child("def main(): return {'done': True}"), "variables.__class__.status")
    state = _parent_state()
    messages = []

    with pytest.raises(InvalidStatePathError, match=r"'variables\.__class__\.status'"):
        await node.run(state, writer=messages.append)

    assert _error_details(messages) == [
        "Variable path 'variables.__class__.status' is not allowed: path segments cannot start with '_'."
    ]
    assert state["variables"].deep_dump() == PARENT


@pytest.fixture
def captured_logs():
    records: list[str] = []
    sink_id = logger.add(records.append, level="WARNING")
    yield records
    logger.remove(sink_id)


async def test_missing_child_flow_streams_the_fact():
    node = _subgraph_node(_python_child("def main(): return {}"), "variables.result")
    node.node_name = "Run B #1 #33"
    node.subgraph_data = None
    messages = []

    with pytest.raises(AttributeError):
        await node.run(_parent_state(), writer=messages.append)

    assert _error_details(messages) == ["Subflow node \"Run B #1\" couldn't start its flow."]


async def test_child_flow_that_cannot_be_built_streams_the_fact(monkeypatch, captured_logs):
    def failing_compile(builder, session_data):
        raise RuntimeError("compile failed at /opt/crew/secret_path.py")

    monkeypatch.setattr(SessionGraphBuilder, "compile_from_schema", failing_compile)
    node = _subgraph_node(_python_child("def main(): return {}"), "variables.result")
    node.node_name = "Run B #1 #33"
    messages = []

    with pytest.raises(RuntimeError):
        await node.run(_parent_state(), writer=messages.append)

    assert _error_details(messages) == ["Subflow node \"Run B #1\" couldn't start flow \"child\"."]
    assert any("/opt/crew/secret_path.py" in record for record in captured_logs)


async def test_child_flow_that_fails_streams_the_fact_after_the_childs_own_error():
    node = _subgraph_node(_python_child("def main(): raise ValueError('boom')"), "variables.result")
    node.node_name = "Run B #1 #33"
    messages = []

    with pytest.raises(ReturnCodeError):
        await node.run(_parent_state(), writer=messages.append)

    assert _error_details(messages)[-1] == "Subflow node \"Run B #1\" couldn't finish flow \"child\"."


class StoppingPythonCodeExecutorService:
    """Behaves like RunPythonCodeService when the session is stopped mid-run."""

    async def run_code(self, *args, **kwargs):
        raise StopSession(status="stop", reason="Token budget reached.")


async def test_stop_inside_the_child_flow_streams_no_subflow_failure():
    node = _subgraph_node(
        _python_child("def main(): return {}"),
        "variables.result",
        python_code_executor_service=StoppingPythonCodeExecutorService(),
    )
    node.node_name = "Run B #1 #33"
    messages = []

    with pytest.raises(StopSession):
        await node.run(_parent_state(), writer=messages.append)

    assert not any("Subflow node" in details for details in _error_details(messages))


async def test_output_path_that_does_not_exist_streams_the_fact():
    node = _subgraph_node(_python_child("def main(): return {'done': True}"), "variables.records[5]")
    node.node_name = "Run B #1 #33"
    state = _parent_state()
    messages = []

    with pytest.raises(InvalidStatePathError):
        await node.run(state, writer=messages.append)

    assert _error_details(messages) == [
        "Output path \"variables.records[5]\" of Subflow node \"Run B #1\" doesn't exist."
    ]
    assert state["variables"].deep_dump() == PARENT
