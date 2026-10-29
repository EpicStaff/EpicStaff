"""Test subgraph cycle detection in session data building.

Tests verify that cycles in subgraph references are properly detected and reported,
raising SubGraphValidationError instead of causing RecursionError or 500 errors.
"""

import pytest

from tables.exceptions import SubGraphValidationError
from tables.models import Edge, Graph, PythonCode, PythonNode, StartNode, SubGraphNode
from tables.models.session_models import Session, SessionPrincipal
from tables.services.session_manager_service import SessionManagerService


@pytest.fixture
def service():
    """Provide a SessionManagerService instance."""
    from tables.services.converter_service import ConverterService
    from tables.services.redis_service import RedisService

    # Create minimal service instance for testing
    redis_service = RedisService()
    converter_service = ConverterService()
    return SessionManagerService(redis_service=redis_service, converter_service=converter_service)


def _add_leaf_node(graph, start_node):
    """Give a graph with no subgraph reference a valid entry point via a PythonNode."""
    python_node = PythonNode.objects.create(
        graph=graph,
        node_name="leaf",
        python_code=PythonCode.objects.create(code="def main(): return 1"),
    )
    Edge.objects.create(graph=graph, start_node_id=start_node.pk, end_node_id=python_node.pk)


@pytest.mark.django_db
def test_detects_cycle_not_containing_root(default_org, service):
    """Cycle between B and C, root A not in cycle: A → B ⇄ C.

    This is the critical case: the original implementation would miss this
    because it only checked if a subgraph pointed back to root_graph.id.
    """
    # Create three graphs: A (root), B (child), C (child)
    graph_a = Graph.objects.create(name="Flow A", org=default_org)
    graph_b = Graph.objects.create(name="Flow B", org=default_org)
    graph_c = Graph.objects.create(name="Flow C", org=default_org)

    # Create start nodes for each
    start_a = StartNode.objects.create(graph=graph_a, variables={})
    StartNode.objects.create(graph=graph_b, variables={})
    StartNode.objects.create(graph=graph_c, variables={})

    # Create edges: A references B, B references C, C references B (cycle)
    SubGraphNode.objects.create(graph=graph_a, subgraph=graph_b, node_number=1, node_name="subgraph_b")
    SubGraphNode.objects.create(graph=graph_b, subgraph=graph_c, node_number=1, node_name="subgraph_c")
    SubGraphNode.objects.create(graph=graph_c, subgraph=graph_b, node_number=1, node_name="subgraph_b_again")

    # Create session on root flow
    session = Session.objects.create(
        graph=graph_a, status=Session.SessionStatus.PENDING, variables={}
    )
    SessionPrincipal.objects.create(
        session=session, kind=SessionPrincipal.ActionKind.TRIGGER
    )

    # Building session data should raise SubGraphValidationError, not RecursionError
    with pytest.raises(SubGraphValidationError) as exc_info:
        service.create_session_data(session=session, start_node=start_a)

    # Error message should reference both graphs in the cycle
    error_message = str(exc_info.value.detail)
    assert "Flow B" in error_message or "Flow C" in error_message


@pytest.mark.django_db
def test_detects_cycle_through_root(default_org, service):
    """Cycle through root: A ⇄ B (A references B, B references A)."""
    graph_a = Graph.objects.create(name="Flow A", org=default_org)
    graph_b = Graph.objects.create(name="Flow B", org=default_org)

    start_a = StartNode.objects.create(graph=graph_a, variables={})
    StartNode.objects.create(graph=graph_b, variables={})

    # Create cycle: A → B → A
    SubGraphNode.objects.create(graph=graph_a, subgraph=graph_b, node_number=1, node_name="subgraph_b")
    SubGraphNode.objects.create(graph=graph_b, subgraph=graph_a, node_number=1, node_name="subgraph_a")

    session = Session.objects.create(
        graph=graph_a, status=Session.SessionStatus.PENDING, variables={}
    )
    SessionPrincipal.objects.create(
        session=session, kind=SessionPrincipal.ActionKind.TRIGGER
    )

    with pytest.raises(SubGraphValidationError):
        service.create_session_data(session=session, start_node=start_a)


@pytest.mark.django_db
def test_detects_self_loop(default_org, service):
    """Self-loop: A references itself."""
    graph_a = Graph.objects.create(name="Flow A", org=default_org)
    start_a = StartNode.objects.create(graph=graph_a, variables={})

    # Create self-reference
    SubGraphNode.objects.create(graph=graph_a, subgraph=graph_a, node_number=1, node_name="self_ref")

    session = Session.objects.create(
        graph=graph_a, status=Session.SessionStatus.PENDING, variables={}
    )
    SessionPrincipal.objects.create(
        session=session, kind=SessionPrincipal.ActionKind.TRIGGER
    )

    with pytest.raises(SubGraphValidationError):
        service.create_session_data(session=session, start_node=start_a)


@pytest.mark.django_db
def test_acyclic_diamond_passes(default_org, service):
    """Acyclic diamond DAG: A → B, A → C, B → D, C → D."""
    graph_a = Graph.objects.create(name="Flow A", org=default_org)
    graph_b = Graph.objects.create(name="Flow B", org=default_org)
    graph_c = Graph.objects.create(name="Flow C", org=default_org)
    graph_d = Graph.objects.create(name="Flow D", org=default_org)

    start_a = StartNode.objects.create(graph=graph_a, variables={})
    start_b = StartNode.objects.create(graph=graph_b, variables={})
    start_c = StartNode.objects.create(graph=graph_c, variables={})
    start_d = StartNode.objects.create(graph=graph_d, variables={})

    # Diamond shape: no cycles
    node_ref_b = SubGraphNode.objects.create(
        graph=graph_a, subgraph=graph_b, node_number=1, node_name="ref_b"
    )
    SubGraphNode.objects.create(graph=graph_a, subgraph=graph_c, node_number=2, node_name="ref_c")
    node_ref_d = SubGraphNode.objects.create(
        graph=graph_b, subgraph=graph_d, node_number=1, node_name="ref_d"
    )
    node_ref_d2 = SubGraphNode.objects.create(
        graph=graph_c, subgraph=graph_d, node_number=1, node_name="ref_d2"
    )

    # Each graph needs a valid entry point: the root flow run on, and every
    # subgraph, since _build_graph_data recurses into each of them independently.
    Edge.objects.create(graph=graph_a, start_node_id=start_a.pk, end_node_id=node_ref_b.pk)
    Edge.objects.create(graph=graph_b, start_node_id=start_b.pk, end_node_id=node_ref_d.pk)
    Edge.objects.create(graph=graph_c, start_node_id=start_c.pk, end_node_id=node_ref_d2.pk)
    _add_leaf_node(graph_d, start_d)

    session = Session.objects.create(
        graph=graph_a, status=Session.SessionStatus.PENDING, variables={}
    )
    SessionPrincipal.objects.create(
        session=session, kind=SessionPrincipal.ActionKind.TRIGGER
    )

    # Should not raise
    session_data = service.create_session_data(session=session, start_node=start_a)

    # D should appear exactly once in unique_subgraph_list
    subgraph_ids = [sg.id for sg in session_data.unique_subgraph_list]
    assert subgraph_ids.count(graph_d.id) == 1


@pytest.mark.django_db
def test_deep_acyclic_chain_passes(default_org, service):
    """Deep chain without cycle: A → B → C → D → E."""
    graphs = []
    starts = []
    for i in range(5):
        graphs.append(Graph.objects.create(name=f"Flow {chr(65 + i)}", org=default_org))
        starts.append(StartNode.objects.create(graph=graphs[-1], variables={}))

    # Chain: A → B → C → D → E
    for i in range(len(graphs) - 1):
        ref_node = SubGraphNode.objects.create(
            graph=graphs[i], subgraph=graphs[i + 1],
            node_number=1, node_name=f"ref_{chr(65 + i + 1)}"
        )
        Edge.objects.create(graph=graphs[i], start_node_id=starts[i].pk, end_node_id=ref_node.pk)

    # E is a leaf with no subgraph reference: give it its own entry point.
    _add_leaf_node(graphs[-1], starts[-1])

    session = Session.objects.create(
        graph=graphs[0], status=Session.SessionStatus.PENDING, variables={}
    )
    SessionPrincipal.objects.create(
        session=session, kind=SessionPrincipal.ActionKind.TRIGGER
    )

    # Should not raise
    session_data = service.create_session_data(session=session, start_node=starts[0])

    # All subgraphs should be present
    assert len(session_data.unique_subgraph_list) == 4  # B, C, D, E


@pytest.mark.django_db
def test_deep_chain_with_cycle_at_the_end(default_org, service):
    """Deep chain that cycles at the end: A → B → C → D → B (cycle at D→B)."""
    graph_a = Graph.objects.create(name="Flow A", org=default_org)
    graph_b = Graph.objects.create(name="Flow B", org=default_org)
    graph_c = Graph.objects.create(name="Flow C", org=default_org)
    graph_d = Graph.objects.create(name="Flow D", org=default_org)

    start_a = StartNode.objects.create(graph=graph_a, variables={})
    StartNode.objects.create(graph=graph_b, variables={})
    StartNode.objects.create(graph=graph_c, variables={})
    StartNode.objects.create(graph=graph_d, variables={})

    # Chain with cycle: A → B → C → D → B
    SubGraphNode.objects.create(graph=graph_a, subgraph=graph_b, node_number=1, node_name="ref_b")
    SubGraphNode.objects.create(graph=graph_b, subgraph=graph_c, node_number=1, node_name="ref_c")
    SubGraphNode.objects.create(graph=graph_c, subgraph=graph_d, node_number=1, node_name="ref_d")
    SubGraphNode.objects.create(graph=graph_d, subgraph=graph_b, node_number=1, node_name="back_to_b")

    session = Session.objects.create(
        graph=graph_a, status=Session.SessionStatus.PENDING, variables={}
    )
    SessionPrincipal.objects.create(
        session=session, kind=SessionPrincipal.ActionKind.TRIGGER
    )

    with pytest.raises(SubGraphValidationError):
        service.create_session_data(session=session, start_node=start_a)


@pytest.mark.django_db
def test_null_subgraph_is_ignored(default_org, service):
    """Nullable subgraph field: subgraph=None should be skipped."""
    graph_a = Graph.objects.create(name="Flow A", org=default_org)
    graph_b = Graph.objects.create(name="Flow B", org=default_org)

    start_a = StartNode.objects.create(graph=graph_a, variables={})
    start_b = StartNode.objects.create(graph=graph_b, variables={})

    # Create node with None subgraph and a valid one
    SubGraphNode.objects.create(graph=graph_a, subgraph=None, node_number=1, node_name="null_ref")
    node_valid_ref = SubGraphNode.objects.create(
        graph=graph_a, subgraph=graph_b, node_number=2, node_name="valid_ref"
    )
    Edge.objects.create(graph=graph_a, start_node_id=start_a.pk, end_node_id=node_valid_ref.pk)
    _add_leaf_node(graph_b, start_b)

    session = Session.objects.create(
        graph=graph_a, status=Session.SessionStatus.PENDING, variables={}
    )
    SessionPrincipal.objects.create(
        session=session, kind=SessionPrincipal.ActionKind.TRIGGER
    )

    # Should not raise - null subgraph should be ignored
    session_data = service.create_session_data(session=session, start_node=start_a)

    # Only graph_b should be in unique_subgraphs
    assert len(session_data.unique_subgraph_list) == 1
    assert session_data.unique_subgraph_list[0].id == graph_b.id


@pytest.mark.django_db
def test_soft_deleted_node_does_not_count_as_edge(default_org, service):
    """Soft-deleted SubGraphNode should not create edges in cycle detection."""
    graph_a = Graph.objects.create(name="Flow A", org=default_org)
    graph_b = Graph.objects.create(name="Flow B", org=default_org)

    start_a = StartNode.objects.create(graph=graph_a, variables={})
    start_b = StartNode.objects.create(graph=graph_b, variables={})

    # Create soft-deleted node that points A → B → A
    node_ref_b = SubGraphNode.objects.create(
        graph=graph_a, subgraph=graph_b, node_number=1, node_name="ref_b"
    )
    back_ref = SubGraphNode.objects.create(graph=graph_b, subgraph=graph_a, node_number=1, node_name="back_to_a")
    back_ref.active = False
    back_ref.save(update_fields=["active"])  # Soft delete the cycle-creating edge

    Edge.objects.create(graph=graph_a, start_node_id=start_a.pk, end_node_id=node_ref_b.pk)
    # back_ref is soft-deleted, so B is now a leaf with no (active) subgraph reference.
    _add_leaf_node(graph_b, start_b)

    session = Session.objects.create(
        graph=graph_a, status=Session.SessionStatus.PENDING, variables={}
    )
    SessionPrincipal.objects.create(
        session=session, kind=SessionPrincipal.ActionKind.TRIGGER
    )

    # Should not raise - soft deleted node should be ignored
    session_data = service.create_session_data(session=session, start_node=start_a)

    # Only graph_b should be present (not cyclic anymore)
    assert len(session_data.unique_subgraph_list) == 1
    assert session_data.unique_subgraph_list[0].id == graph_b.id


@pytest.mark.django_db
def test_graph_without_subgraphs_passes(default_org, service):
    """Simple graph with no subgraph references."""
    graph_a = Graph.objects.create(name="Flow A", org=default_org)
    start_a = StartNode.objects.create(graph=graph_a, variables={})
    _add_leaf_node(graph_a, start_a)

    session = Session.objects.create(
        graph=graph_a, status=Session.SessionStatus.PENDING, variables={}
    )
    SessionPrincipal.objects.create(
        session=session, kind=SessionPrincipal.ActionKind.TRIGGER
    )

    # Should not raise
    session_data = service.create_session_data(session=session, start_node=start_a)

    # No subgraphs
    assert len(session_data.unique_subgraph_list) == 0
