from __future__ import annotations

from types import SimpleNamespace

from dotdict import DotDict
from langgraph.graph import StateGraph

from models.state import State
from services.graph.subgraphs.subgraph_node import SubGraphNode
from src.shared.models.graph_nodes import SubGraphNodeData


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


def test_state_history_variables_snapshot_is_detached_from_later_mutations():
    node = _make_subgraph_node(output_variable_path="variables.a.b")
    state = _make_parent_state()

    updated = node._process_subgraph_result(
        state, subgraph_input={}, result=_make_result({"out": "subgraph_value"})
    )
    history_variables = updated["state_history"][0]["variables"]

    assert history_variables["a"]["b"] == {"out": "subgraph_value"}
    assert history_variables["a"] is not state["variables"].a
