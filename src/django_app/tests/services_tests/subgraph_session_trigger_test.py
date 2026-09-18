from uuid import uuid4

import pytest
from django.utils import timezone

from tables.models.graph_models import Graph, GraphSessionMessage
from tables.models.session_models import Session, SessionTrigger
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
def test_create_subgraph_sessions_creates_parent_flow_trigger_rows(default_org):
    root_graph = Graph.objects.create(name="root", org=default_org)
    child_graph = Graph.objects.create(name="child", org=default_org)
    root_session = Session.objects.create(
        graph=root_graph, status=Session.SessionStatus.END, variables={}
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
def test_create_subgraph_sessions_creates_one_trigger_row_per_child(default_org):
    root_graph = Graph.objects.create(name="root2", org=default_org)
    child_graph_a = Graph.objects.create(name="child_a", org=default_org)
    child_graph_b = Graph.objects.create(name="child_b", org=default_org)
    root_session = Session.objects.create(
        graph=root_graph, status=Session.SessionStatus.END, variables={}
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
