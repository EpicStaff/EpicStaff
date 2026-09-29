from uuid import uuid4

import pytest
from django.utils import timezone

from tables.models.graph_models import Graph, GraphSessionMessage
from tables.models.session_models import Session, SessionPrincipal, SessionTrigger
from tables.services.redis_pubsub import RedisPubSub


def _create_subgraph_message(session, message_type, subgraph_execution_id, **extra):
    return GraphSessionMessage.objects.create(
        session=session,
        created_at=timezone.now(),
        message_data={
            "message_type": message_type,
            "subgraph_execution_id": subgraph_execution_id,
            **extra,
        },
        uuid=uuid4(),
    )


@pytest.mark.django_db
def test_create_subgraph_sessions_creates_parent_flow_trigger_rows(
    default_org, regular_user
):
    root_graph = Graph.objects.create(name="root", org=default_org)
    child_graph = Graph.objects.create(name="child", org=default_org)
    root_session = Session.objects.create(
        graph=root_graph, status=Session.SessionStatus.END, variables={}
    )
    SessionPrincipal.objects.create(
        session=root_session,
        kind=SessionPrincipal.ActionKind.USER,
        user=regular_user,
        email=regular_user.email,
    )

    _create_subgraph_message(
        root_session,
        "subgraph_start",
        "exec-1",
        subgraph_id=child_graph.id,
        input={},
        subgraph_execution_ids=[],
    )
    _create_subgraph_message(
        root_session, "subgraph_finish", "exec-1", output={"result": "ok"}
    )

    RedisPubSub()._create_subgraph_sessions(root_session.id)

    child_session = Session.objects.get(parent_session=root_session)

    assert child_session.trigger.trigger_type == SessionTrigger.TriggerType.PARENT_FLOW
    assert child_session.trigger.triggered_by_session_id == root_session.id


@pytest.mark.django_db
def test_create_subgraph_sessions_creates_one_trigger_row_per_child(
    default_org, regular_user
):
    root_graph = Graph.objects.create(name="root2", org=default_org)
    child_graph_a = Graph.objects.create(name="child_a", org=default_org)
    child_graph_b = Graph.objects.create(name="child_b", org=default_org)
    root_session = Session.objects.create(
        graph=root_graph, status=Session.SessionStatus.END, variables={}
    )
    SessionPrincipal.objects.create(
        session=root_session,
        kind=SessionPrincipal.ActionKind.USER,
        user=regular_user,
        email=regular_user.email,
    )

    _create_subgraph_message(
        root_session,
        "subgraph_start",
        "exec-a",
        subgraph_id=child_graph_a.id,
        input={},
        subgraph_execution_ids=[],
    )
    _create_subgraph_message(root_session, "subgraph_finish", "exec-a", output={})
    _create_subgraph_message(
        root_session,
        "subgraph_start",
        "exec-b",
        subgraph_id=child_graph_b.id,
        input={},
        subgraph_execution_ids=[],
    )
    _create_subgraph_message(root_session, "subgraph_finish", "exec-b", output={})

    RedisPubSub()._create_subgraph_sessions(root_session.id)

    child_sessions = Session.objects.filter(parent_session=root_session)

    assert child_sessions.count() == 2
    assert (
        SessionTrigger.objects.filter(
            session__in=child_sessions,
            trigger_type=SessionTrigger.TriggerType.PARENT_FLOW,
            triggered_by_session_id=root_session.id,
        ).count()
        == 2
    )


@pytest.mark.django_db
def test_create_subgraph_sessions_copies_root_principal_for_user_run(
    default_org, regular_user
):
    # EST-4126: subgraph (subflow) sessions were left with no SessionPrincipal at
    # all, so the acting user was lost on any child session and export crashed.
    # The child's principal must mirror the root's, not be marked as automation.
    root_graph = Graph.objects.create(name="root-principal", org=default_org)
    child_graph = Graph.objects.create(name="child-principal", org=default_org)
    root_session = Session.objects.create(
        graph=root_graph, status=Session.SessionStatus.END, variables={}
    )
    SessionPrincipal.objects.create(
        session=root_session,
        kind=SessionPrincipal.ActionKind.USER,
        user=regular_user,
        email=regular_user.email,
    )

    _create_subgraph_message(
        root_session,
        "subgraph_start",
        "exec-principal",
        subgraph_id=child_graph.id,
        input={},
        subgraph_execution_ids=[],
    )
    _create_subgraph_message(
        root_session, "subgraph_finish", "exec-principal", output={"result": "ok"}
    )

    RedisPubSub()._create_subgraph_sessions(root_session.id)

    child_session = Session.objects.get(parent_session=root_session)
    principal = child_session.principal

    assert principal.kind == SessionPrincipal.ActionKind.USER
    assert principal.user_id == regular_user.id
    assert principal.email == regular_user.email
    assert principal.api_key_id is None


@pytest.mark.django_db
def test_create_subgraph_sessions_copies_root_principal_for_trigger_run(default_org):
    # A root session started by automation (no named actor) must propagate that
    # honestly to its subgraph children, rather than fabricating a user.
    root_graph = Graph.objects.create(name="root-trigger-principal", org=default_org)
    child_graph = Graph.objects.create(name="child-trigger-principal", org=default_org)
    root_session = Session.objects.create(
        graph=root_graph, status=Session.SessionStatus.END, variables={}
    )
    SessionPrincipal.objects.create(
        session=root_session, kind=SessionPrincipal.ActionKind.TRIGGER
    )

    _create_subgraph_message(
        root_session,
        "subgraph_start",
        "exec-trigger",
        subgraph_id=child_graph.id,
        input={},
        subgraph_execution_ids=[],
    )
    _create_subgraph_message(
        root_session, "subgraph_finish", "exec-trigger", output={"result": "ok"}
    )

    RedisPubSub()._create_subgraph_sessions(root_session.id)

    child_session = Session.objects.get(parent_session=root_session)
    principal = child_session.principal

    assert principal.kind == SessionPrincipal.ActionKind.TRIGGER
    assert principal.user_id is None
    assert principal.api_key_id is None
    assert principal.email is None


@pytest.mark.django_db
def test_create_subgraph_sessions_copies_root_principal_to_every_child(
    default_org, regular_user
):
    root_graph = Graph.objects.create(name="root-multi-principal", org=default_org)
    child_graph_a = Graph.objects.create(name="child-a-principal", org=default_org)
    child_graph_b = Graph.objects.create(name="child-b-principal", org=default_org)
    root_session = Session.objects.create(
        graph=root_graph, status=Session.SessionStatus.END, variables={}
    )
    SessionPrincipal.objects.create(
        session=root_session,
        kind=SessionPrincipal.ActionKind.USER,
        user=regular_user,
        email=regular_user.email,
    )

    _create_subgraph_message(
        root_session,
        "subgraph_start",
        "exec-multi-a",
        subgraph_id=child_graph_a.id,
        input={},
        subgraph_execution_ids=[],
    )
    _create_subgraph_message(root_session, "subgraph_finish", "exec-multi-a", output={})
    _create_subgraph_message(
        root_session,
        "subgraph_start",
        "exec-multi-b",
        subgraph_id=child_graph_b.id,
        input={},
        subgraph_execution_ids=[],
    )
    _create_subgraph_message(root_session, "subgraph_finish", "exec-multi-b", output={})

    RedisPubSub()._create_subgraph_sessions(root_session.id)

    child_sessions = Session.objects.filter(parent_session=root_session)

    assert child_sessions.count() == 2
    assert (
        SessionPrincipal.objects.filter(
            session__in=child_sessions,
            kind=SessionPrincipal.ActionKind.USER,
            user=regular_user,
        ).count()
        == 2
    )
