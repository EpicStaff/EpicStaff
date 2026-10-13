from __future__ import annotations

from types import SimpleNamespace

import pytest
from dotdict import DotDict
from langgraph.graph import StateGraph

from models.graph_models import FinishMessageData, GraphMessage
from models.state import State
from services.graph.events import StopEvent
from services.graph.graph_builder import SessionGraphBuilder
from services.graph.subgraphs.subgraph_node import SubGraphNode
from src.shared.models import (
    EdgeData,
    GraphData,
    PythonCodeData,
    PythonNodeData,
    SubGraphData,
)
from src.shared.models.graph_nodes import SubGraphNodeData
from tests.graph.rebuild_counting_dict import RebuildCountingDict
from tests.graph.test_graph_builder import FakePythonCodeExecutorService


def _make_subgraph_node(output_variable_path: str) -> SubGraphNode:
    subgraph_node_data = SubGraphNodeData(
        node_name="sub_node",
        subgraph_id=1,
        input_map={},
        output_variable_path=output_variable_path,
    )
    return SubGraphNode(
        session_id=1,
        subgraph_node_data=subgraph_node_data,
        unique_subgraph_list=[],
        graph_builder=StateGraph(State),
        org_id=1,
    )


def _make_parent_state() -> dict:
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


def _make_result(variables: dict) -> dict:
    return {"variables": DotDict(variables)}


def test_create_subgraph_builder_does_not_raise_and_inherits_services():
    """Regression test for the dead `crewai_output_channel` kwarg: the
    parent test double below only exposes the services SessionGraphBuilder
    actually accepts. If `_create_subgraph_builder` still reads or passes
    `crewai_output_channel`, this raises AttributeError/TypeError."""
    parent_builder = SimpleNamespace(
        redis_service=SimpleNamespace(name="redis"),
        python_code_executor_service=SimpleNamespace(name="python_code_executor"),
        knowledge_search_service=SimpleNamespace(name="knowledge_search"),
        agent_task_service=SimpleNamespace(name="agent_task"),
        key_value_client=SimpleNamespace(name="key_value_client"),
    )
    node = _make_subgraph_node(output_variable_path="variables.result")
    node.session_graph_builder = parent_builder

    subgraph_builder = node._create_subgraph_builder()

    assert subgraph_builder.redis_service is parent_builder.redis_service
    assert (
        subgraph_builder.python_code_executor_service
        is parent_builder.python_code_executor_service
    )
    assert (
        subgraph_builder.knowledge_search_service
        is parent_builder.knowledge_search_service
    )
    assert subgraph_builder.agent_task_service is parent_builder.agent_task_service
    assert subgraph_builder.key_value_client is parent_builder.key_value_client


def test_nested_output_path_does_not_mutate_parent_variables():
    node = _make_subgraph_node(output_variable_path="variables.a.b")
    state = _make_parent_state()
    snapshot = state["variables"].deep_dump()

    updated = node._process_subgraph_result(
        state, subgraph_input={}, result=_make_result({"out": "subgraph_value"})
    )

    assert state["variables"].deep_dump() == snapshot
    assert state["variables"].a.b == "parent_value"
    assert updated["variables"].a.b == {"out": "subgraph_value"}
    assert updated["variables"].a.keep == "untouched"


def test_existing_dict_output_path_merges_into_copy_not_parent():
    node = _make_subgraph_node(output_variable_path="variables.a")
    state = _make_parent_state()
    snapshot = state["variables"].deep_dump()

    updated = node._process_subgraph_result(
        state, subgraph_input={}, result=_make_result({"b": "subgraph_value"})
    )

    assert state["variables"].deep_dump() == snapshot
    assert updated["variables"].a.b == "subgraph_value"
    assert updated["variables"].a.keep == "untouched"


def test_parent_nested_containers_are_not_shared_with_result():
    node = _make_subgraph_node(output_variable_path="variables.new_key")
    state = _make_parent_state()
    snapshot = state["variables"].deep_dump()

    updated = node._process_subgraph_result(
        state, subgraph_input={}, result=_make_result({"out": 1})
    )

    assert updated["variables"].a is not state["variables"].a
    assert updated["variables"].records is not state["variables"].records
    assert updated["variables"].records[0] is not state["variables"].records[0]

    updated["variables"].a.b = "mutated"
    updated["variables"].records[0].name = "mutated"
    updated["variables"].records.append({"name": "third"})
    updated["variables"].scalar = 99

    assert state["variables"].deep_dump() == snapshot


def test_state_history_item_has_no_variables_snapshot():
    """Each history item travels with every later message and sandbox call,
    so a full variables snapshot per subgraph run would grow without bound."""
    node = _make_subgraph_node(output_variable_path="variables.a.b")
    state = _make_parent_state()

    updated = node._process_subgraph_result(
        state, subgraph_input={}, result=_make_result({"out": "subgraph_value"})
    )

    assert "variables" not in updated["state_history"][0]


def test_whole_variables_output_path_deep_merges_into_parent():
    """When output_variable_path='variables', subgraph output is deep-merged
    into the parent variables — matching Python node behaviour."""
    node = _make_subgraph_node(output_variable_path="variables")
    state = _make_parent_state()
    # Subgraph returns a.b (overwrites) but NOT a.keep or scalar
    result = _make_result({"a": {"b": "sub_value"}, "new_var": 42})

    updated = node._process_subgraph_result(state, subgraph_input={}, result=result)

    # Subgraph value merged in
    assert updated["variables"].a.b == "sub_value"
    assert updated["variables"].new_var == 42
    # Parent-only keys preserved (not wiped)
    assert updated["variables"].a.keep == "untouched"
    assert updated["variables"].scalar == 1
    assert len(updated["variables"].records) == 2


def test_whole_variables_output_path_does_not_alias_subgraph_containers():
    """When output_variable_path='variables', returned containers should not alias the result."""
    node = _make_subgraph_node(output_variable_path="variables")
    state = _make_parent_state()
    result = _make_result({"a": {"b": "sub"}})

    updated = node._process_subgraph_result(state, subgraph_input={}, result=result)

    # The nested dict should be a deep copy, not an alias
    assert updated["variables"].a is not result["variables"].a

    # Mutating the copy should not affect the original
    updated["variables"].a["b"] = "mutated"
    assert result["variables"].a["b"] == "sub"


def test_whole_variables_output_path_keeps_state_history_immutable():
    """State history should not be affected by mutations to returned variables when output_path is 'variables'."""
    from utils.set_output_variables import set_output_variables

    node = _make_subgraph_node(output_variable_path="variables")
    state = _make_parent_state()
    result = _make_result({"a": {"b": "sub"}})

    updated = node._process_subgraph_result(state, subgraph_input={}, result=result)
    history = updated["state_history"][0]

    assert history["output"]["a"]["b"] == "sub"

    # Mutate the returned variables
    set_output_variables(updated, "variables.a.b", "later")

    # The history should still have the original values
    assert history["output"]["a"]["b"] == "sub"


@pytest.mark.parametrize(
    "output_path", ["variables", "variables.a", "variables.a.b", "variables.new_key"]
)
def test_state_history_output_is_detached_from_returned_variables(output_path):
    """State history output should not share references with returned variables,
    regardless of which output_variable_path branch produced them."""
    node = _make_subgraph_node(output_variable_path=output_path)
    state = _make_parent_state()
    # "a" and "records" mirror the parent state's own top-level keys so that every branch
    # (whole-replace at "variables", or merge/overwrite via set_output_variables) ends up
    # with both keys present at the top level.
    result = _make_result({"a": {"b": "sub"}, "records": [{"name": "sub_record"}]})

    updated = node._process_subgraph_result(state, subgraph_input={}, result=result)
    history = updated["state_history"][0]

    if output_path == "variables":
        returned_a, returned_records = updated["variables"].a, updated["variables"].records
    else:
        written = updated["variables"]
        for key in output_path.split(".")[1:]:
            written = written[key]
        returned_a, returned_records = written.a, written.records

    assert history["output"]["a"] is not returned_a
    assert history["output"]["records"] is not returned_records



class FakeCompiledSubgraph:
    def __init__(self, chunks):
        self._chunks = chunks

    async def astream(self, state, config, stream_mode):
        for chunk in self._chunks:
            yield chunk


@pytest.mark.asyncio
async def test_inner_messages_are_tagged_with_the_subgraph_run_without_being_rebuilt():
    node = _make_subgraph_node(output_variable_path="variables.result")
    output = RebuildCountingDict(answer=RebuildCountingDict(text="ok"))
    message_data = FinishMessageData(output=output, state={})
    inner_message = GraphMessage(
        session_id=1, name="inner", execution_order=0, message_data=message_data
    )
    final_values = {"variables": DotDict({"done": True})}
    written = []
    RebuildCountingDict.constructions = 0

    result = await node._execute_subgraph(
        FakeCompiledSubgraph([("custom", inner_message), ("values", final_values)]),
        subgraph_state={},
        writer=written.append,
        subgraph_execution_id="run-2",
    )

    assert result is final_values
    [forwarded] = written
    assert forwarded.message_data["subgraph_execution_ids"] == ["run-2"]
    assert forwarded.message_data["output"] is output
    assert RebuildCountingDict.constructions == 0
    assert not hasattr(message_data, "subgraph_execution_ids")


def _make_doubling_subgraph_node() -> SubGraphNode:
    child_graph = GraphData(
        name="child",
        entrypoint="double",
        end_node=None,
        python_node_list=[
            PythonNodeData(
                node_name="double",
                python_code=PythonCodeData(
                    venv_name="venv-default",
                    code="def main(x): return x * 2",
                    entrypoint="main",
                    libraries=[],
                    global_kwargs={},
                ),
                input_map={"x": "variables.x"},
                output_variable_path="variables.doubled",
            )
        ],
        edge_list=[EdgeData(start_key="double", end_key="__end__")],
    )
    parent_builder = SimpleNamespace(
        redis_service=None,
        python_code_executor_service=FakePythonCodeExecutorService(),
        knowledge_search_service=None,
        agent_task_service=None,
        key_value_client=None,
    )
    return SubGraphNode(
        session_id=1,
        subgraph_node_data=SubGraphNodeData(
            node_name="sub_node",
            subgraph_id=7,
            input_map={"x": "variables.x"},
            output_variable_path="variables.result",
        ),
        unique_subgraph_list=[SubGraphData(id=7, data=child_graph)],
        graph_builder=StateGraph(State),
        org_id=1,
        session_graph_builder=parent_builder,
        stop_event=StopEvent(),
    )


@pytest.mark.asyncio
async def test_compiled_subgraph_is_reused_across_runs_with_fresh_state(monkeypatch):
    node = _make_doubling_subgraph_node()
    compile_calls = []
    real_compile = SessionGraphBuilder.compile_from_schema

    def counting_compile(builder, session_data):
        compile_calls.append(session_data)
        return real_compile(builder, session_data)

    monkeypatch.setattr(SessionGraphBuilder, "compile_from_schema", counting_compile)

    state = _make_parent_state()
    state["variables"].x = 2
    first = await node.run(state, writer=lambda message: None)
    first["variables"].x = 5
    second = await node.run(first, writer=lambda message: None)

    assert len(compile_calls) == 1
    assert second["variables"].result.doubled == 10
    first_item, second_item = second["state_history"]
    assert first_item["output"]["doubled"] == 4
    assert second_item["output"]["doubled"] == 10
