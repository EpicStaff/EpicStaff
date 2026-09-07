from __future__ import annotations

from types import SimpleNamespace

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
