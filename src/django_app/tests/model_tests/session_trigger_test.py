import pytest

from tables.models import PythonCode
from tables.models.graph_models import (
    ScheduleTriggerNode,
    TelegramTriggerNode,
    WebhookTriggerNode,
)
from tables.models.session_models import Session, SessionTrigger
from tables.serializers.model_serializers.session_serializers import (
    SessionLightSerializer,
    SessionSerializer,
)


@pytest.fixture
def session(graph) -> Session:
    return Session.objects.create(
        graph=graph, status=Session.SessionStatus.PENDING, variables={}
    )


@pytest.fixture
def schedule_trigger_node(graph) -> ScheduleTriggerNode:
    return ScheduleTriggerNode.objects.create(graph=graph, node_name="schedule_node")


@pytest.fixture
def webhook_trigger_node(graph) -> WebhookTriggerNode:
    python_code = PythonCode.objects.create(code="def main(): return None")
    return WebhookTriggerNode.objects.create(
        graph=graph, node_name="webhook_node", python_code=python_code
    )


@pytest.fixture
def telegram_trigger_node(graph) -> TelegramTriggerNode:
    return TelegramTriggerNode.objects.create(graph=graph, node_name="telegram_node")


@pytest.mark.django_db
def test_trigger_id_returns_schedule_node_id_for_schedule_trigger(
    session, schedule_trigger_node
):
    trigger = SessionTrigger.objects.create(
        session=session,
        trigger_type=SessionTrigger.TriggerType.SCHEDULE,
        schedule_trigger_node=schedule_trigger_node,
    )

    assert trigger.trigger_id == schedule_trigger_node.id


@pytest.mark.django_db
def test_trigger_id_returns_webhook_node_id_for_webhook_trigger(
    session, webhook_trigger_node
):
    trigger = SessionTrigger.objects.create(
        session=session,
        trigger_type=SessionTrigger.TriggerType.WEBHOOK,
        webhook_trigger_node=webhook_trigger_node,
    )

    assert trigger.trigger_id == webhook_trigger_node.id


@pytest.mark.django_db
def test_trigger_id_returns_telegram_node_id_for_telegram_trigger(
    session, telegram_trigger_node
):
    trigger = SessionTrigger.objects.create(
        session=session,
        trigger_type=SessionTrigger.TriggerType.TELEGRAM,
        telegram_trigger_node=telegram_trigger_node,
    )

    assert trigger.trigger_id == telegram_trigger_node.id


@pytest.mark.django_db
def test_trigger_id_returns_parent_session_id_for_parent_flow_trigger(session, graph):
    parent_session = Session.objects.create(
        graph=graph, status=Session.SessionStatus.END, variables={}
    )
    trigger = SessionTrigger.objects.create(
        session=session,
        trigger_type=SessionTrigger.TriggerType.PARENT_FLOW,
        triggered_by_session=parent_session,
    )

    assert trigger.trigger_id == parent_session.id


@pytest.mark.django_db
def test_trigger_id_is_none_for_manual_trigger(session):
    trigger = SessionTrigger.objects.create(
        session=session, trigger_type=SessionTrigger.TriggerType.MANUAL
    )

    assert trigger.trigger_id is None


@pytest.mark.django_db
def test_session_without_trigger_row_serializes_trigger_as_none(session):
    assert SessionSerializer(session).data["trigger"] is None
    assert SessionLightSerializer(session).data["trigger"] is None


@pytest.mark.django_db
def test_session_with_trigger_row_serializes_trigger_type_and_id(
    session, schedule_trigger_node
):
    SessionTrigger.objects.create(
        session=session,
        trigger_type=SessionTrigger.TriggerType.SCHEDULE,
        schedule_trigger_node=schedule_trigger_node,
    )

    data = SessionSerializer(session).data["trigger"]

    assert data["trigger_type"] == SessionTrigger.TriggerType.SCHEDULE
    assert data["trigger_id"] == schedule_trigger_node.id


@pytest.mark.django_db
def test_deleting_schedule_node_leaves_trigger_row_with_node_name_and_nulled_fk(
    session, schedule_trigger_node
):
    trigger = SessionTrigger.objects.create(
        session=session,
        trigger_type=SessionTrigger.TriggerType.SCHEDULE,
        node_name=schedule_trigger_node.node_name,
        schedule_trigger_node=schedule_trigger_node,
    )

    schedule_trigger_node.delete()
    trigger.refresh_from_db()

    assert trigger.schedule_trigger_node_id is None
    assert trigger.node_name == "schedule_node"
    assert trigger.trigger_id is None
