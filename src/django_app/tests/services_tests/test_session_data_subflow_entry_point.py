"""A run whose subflow has nothing connected to its Start names that subflow and its node."""

import pytest

from tables.exceptions import GraphEntryPointException, SubflowEntryPointException
from tables.models import Edge, Graph, PythonCode, PythonNode, StartNode, SubGraphNode
from tables.models.session_models import Session, SessionPrincipal
from tables.services.converter_service import ConverterService
from tables.services.redis_service import RedisService
from tables.services.session_manager_service import SessionManagerService


@pytest.fixture
def service():
    return SessionManagerService(redis_service=RedisService(), converter_service=ConverterService())


def _connect_leaf_node(graph, start_node):
    python_node = PythonNode.objects.create(
        graph=graph,
        node_name="leaf",
        python_code=PythonCode.objects.create(code="def main(): return 1"),
    )
    Edge.objects.create(graph=graph, start_node_id=start_node.pk, end_node_id=python_node.pk)


def _build_session_data(service, graph, start_node):
    session = Session.objects.create(graph=graph, status=Session.SessionStatus.PENDING, variables={})
    SessionPrincipal.objects.create(session=session, kind=SessionPrincipal.ActionKind.TRIGGER)
    return service.create_session_data(session=session, start_node=start_node)


@pytest.mark.django_db
@pytest.mark.parametrize("child_has_start_node", [True, False])
def test_subflow_with_nothing_connected_to_start_is_named_with_its_node(
    default_org, service, child_has_start_node
):
    parent = Graph.objects.create(name="Parent", org=default_org)
    child = Graph.objects.create(name="Child", org=default_org)
    parent_start = StartNode.objects.create(graph=parent, variables={})
    _connect_leaf_node(parent, parent_start)
    if child_has_start_node:
        StartNode.objects.create(graph=child, variables={})
    # Not connected to anything: the run would never reach it.
    SubGraphNode.objects.create(graph=parent, subgraph=child, node_number=3, node_name="Parse")

    with pytest.raises(SubflowEntryPointException) as exc_info:
        _build_session_data(service, parent, parent_start)

    assert str(exc_info.value.detail) == (
        'Flow "Child" (used by Subflow node "Parse #3") has no node connected to its Start.'
    )
    assert exc_info.value.status_code == 400
    assert exc_info.value.get_codes() == "subflow_entry_point_missing"


@pytest.mark.django_db
def test_nested_subflow_names_the_flow_with_nothing_connected_and_the_node_inside_its_parent(
    default_org, service
):
    flow_a = Graph.objects.create(name="Flow A", org=default_org)
    flow_b = Graph.objects.create(name="Flow B", org=default_org)
    flow_c = Graph.objects.create(name="Flow C", org=default_org)
    start_a = StartNode.objects.create(graph=flow_a, variables={})
    start_b = StartNode.objects.create(graph=flow_b, variables={})
    StartNode.objects.create(graph=flow_c, variables={})
    uses_b = SubGraphNode.objects.create(
        graph=flow_a, subgraph=flow_b, node_number=1, node_name="Run B"
    )
    Edge.objects.create(graph=flow_a, start_node_id=start_a.pk, end_node_id=uses_b.pk)
    uses_c = SubGraphNode.objects.create(
        graph=flow_b, subgraph=flow_c, node_number=2, node_name="Run C"
    )
    Edge.objects.create(graph=flow_b, start_node_id=start_b.pk, end_node_id=uses_c.pk)

    with pytest.raises(SubflowEntryPointException) as exc_info:
        _build_session_data(service, flow_a, start_a)

    assert str(exc_info.value.detail) == (
        'Flow "Flow C" (used by Subflow node "Run C #2") has no node connected to its Start.'
    )


@pytest.mark.django_db
def test_flow_run_with_nothing_connected_to_its_own_start_keeps_the_generic_message(
    default_org, service
):
    flow = Graph.objects.create(name="Flow A", org=default_org)
    start = StartNode.objects.create(graph=flow, variables={})

    with pytest.raises(GraphEntryPointException) as exc_info:
        _build_session_data(service, flow, start)

    assert type(exc_info.value) is GraphEntryPointException
    assert str(exc_info.value.detail) == "No node connected to start node"
