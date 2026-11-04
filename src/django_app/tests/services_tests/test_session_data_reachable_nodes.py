"""The session data of a run holds only the nodes the run reaches, and checks only those."""

import pytest

from tables.exceptions import AgentNodeRunValidationError
from tables.models import Edge, Graph, PythonCode, PythonNode, StartNode
from tables.models.graph_models import (
    AgentNode,
    AgentNodeTask,
    EndNode,
    SubGraphNode,
    TelegramTriggerNode,
)
from tables.models.session_models import Session, SessionPrincipal
from tables.services.session_manager_service import SessionManagerService
from tests.fixtures import *
from utils.graph_utils import runtime_node_name


def _python_node(graph: Graph, node_name: str, node_number: int) -> PythonNode:
    return PythonNode.objects.create(
        graph=graph,
        node_name=node_name,
        node_number=node_number,
        python_code=PythonCode.objects.create(code="def main(): return 1"),
    )


def _agent_node_without_agent(graph: Graph) -> AgentNode:
    agent_node = AgentNode.objects.create(graph=graph, node_name="Writer", node_number=2)
    AgentNodeTask.objects.create(agent_node=agent_node, name="Draft", order=0)
    return agent_node


def _edge(graph: Graph, start, end) -> None:
    Edge.objects.create(graph=graph, start_node_id=start.id, end_node_id=end.id)


def _session(graph: Graph, entrypoint: str | None = None) -> Session:
    session = Session.objects.create(
        graph=graph, status=Session.SessionStatus.PENDING, variables={}, entrypoint=entrypoint
    )
    SessionPrincipal.objects.create(session=session, kind=SessionPrincipal.ActionKind.TRIGGER)
    return session


@pytest.fixture
def flow(default_org) -> Graph:
    return Graph.objects.create(name="Leads", org=default_org)


@pytest.mark.django_db
def test_nodes_edges_subflows_and_end_the_run_does_not_reach_are_left_out(flow, default_org):
    start = StartNode.objects.create(graph=flow, variables={})
    prepare = _python_node(flow, "Prepare", 1)
    _edge(flow, start, prepare)
    unconnected = _python_node(flow, "Draft", 3)
    unconnected_end = EndNode.objects.create(graph=flow, output_map={})
    _edge(flow, unconnected, unconnected_end)
    child_flow = Graph.objects.create(name="Invoice parser", org=default_org)
    SubGraphNode.objects.create(graph=flow, node_name="Parse", node_number=4, subgraph=child_flow)

    session_data = SessionManagerService().create_session_data(
        _session(flow), start_node=start
    )

    graph_data = session_data.graph
    assert [node.node_name for node in graph_data.python_node_list] == [
        runtime_node_name(node_name="Prepare", node_number=1, node_id=prepare.id)
    ]
    assert graph_data.entrypoint == graph_data.python_node_list[0].node_name
    assert graph_data.edge_list == []
    assert graph_data.subgraph_node_list == []
    assert graph_data.end_node is None
    assert session_data.unique_subgraph_list == []



@pytest.mark.django_db
def test_end_node_a_route_leads_to_is_sent(flow):
    start = StartNode.objects.create(graph=flow, variables={})
    prepare = _python_node(flow, "Prepare", 1)
    end_node = EndNode.objects.create(graph=flow, output_map={"summary": "variables.summary"})
    _edge(flow, start, prepare)
    _edge(flow, prepare, end_node)

    session_data = SessionManagerService().create_session_data(
        _session(flow), start_node=start
    )

    assert session_data.graph.end_node is not None
    assert session_data.graph.end_node.output_map == {"summary": "variables.summary"}

@pytest.mark.django_db
def test_run_started_by_a_trigger_checks_what_the_trigger_reaches_not_start(flow):
    start = StartNode.objects.create(graph=flow, variables={})
    _edge(flow, start, _agent_node_without_agent(flow))
    trigger = TelegramTriggerNode.objects.create(graph=flow, node_name="Bot", node_number=5)
    prepare = _python_node(flow, "Prepare", 1)
    _edge(flow, trigger, prepare)
    entrypoint = runtime_node_name(node_name="Bot", node_number=5, node_id=trigger.id)

    session_data = SessionManagerService().create_session_data(
        _session(flow, entrypoint=entrypoint), start_node=start
    )

    graph_data = session_data.graph
    assert graph_data.entrypoint == entrypoint
    assert graph_data.agent_node_list == []
    assert len(graph_data.python_node_list) == 1
    assert len(graph_data.telegram_trigger_node_data_list) == 1


@pytest.mark.django_db
def test_entrypoint_naming_no_node_of_the_flow_checks_every_node(flow):
    start = StartNode.objects.create(graph=flow, variables={})
    _edge(flow, start, _python_node(flow, "Prepare", 1))
    _agent_node_without_agent(flow)

    with pytest.raises(AgentNodeRunValidationError) as error:
        SessionManagerService().create_session_data(
            _session(flow, entrypoint="Removed trigger #999999"), start_node=start
        )

    assert str(error.value.detail) == 'Agent node "Writer #2" has no agent chosen.'
