import pytest
from django.db import IntegrityError

from tables.models.graph_models import (
    Graph,
    ScheduleTriggerNode,
    TelegramTriggerNode,
    WebhookTriggerNode,
)
from tables.models.python_models import PythonCode
from tables.models.session_models import Session, SessionTrigger
from tables.models.webhook_models import WebhookTrigger
from tables.services.schedule_trigger_service import ScheduleTriggerService
from tables.services.session_manager_service import SessionManagerService
from tables.services.telegram_trigger_service import TelegramTriggerService
from tables.services.trigger_spec import TriggerSpec
from tables.services.webhook_trigger_service import WebhookTriggerService


class _FakeGraphDump:
    def model_dump(self, mode=None):
        return {}


class _FakeSessionData:
    graph = _FakeGraphDump()


def _stub_publish(monkeypatch, session_manager: SessionManagerService | None = None):
    """Stub the run_session tail (SessionData build + Redis publish) so tests
    don't need a fully built graph or a live Redis connection."""
    sm = session_manager or SessionManagerService()
    monkeypatch.setattr(sm, "create_session_data", lambda session: _FakeSessionData())
    monkeypatch.setattr(
        sm.redis_service, "publish_session_data", lambda session_data: 2
    )
    return sm


@pytest.mark.django_db
def test_schedule_trigger_creates_session_trigger_row(default_org, monkeypatch):
    graph = Graph.objects.create(name="sched", org=default_org)
    node = ScheduleTriggerNode.objects.create(graph=graph, node_name="my_schedule")

    _stub_publish(monkeypatch)

    ScheduleTriggerService()._start_session(node)

    session = Session.objects.filter(graph=graph).order_by("-id").first()
    trigger = session.trigger

    assert trigger.trigger_type == SessionTrigger.TriggerType.SCHEDULE
    assert trigger.schedule_trigger_node_id == node.id
    assert trigger.node_name == "my_schedule"
    assert session.entrypoint == f"my_schedule #{node.id}"


@pytest.mark.django_db
def test_webhook_trigger_creates_session_trigger_row(default_org, monkeypatch):
    graph = Graph.objects.create(name="wh", org=default_org)
    webhook_trigger = WebhookTrigger.objects.create(path="wpath")
    python_code = PythonCode.objects.create(code="def main(): return None")
    node = WebhookTriggerNode.objects.create(
        graph=graph,
        node_name="my_webhook",
        webhook_trigger=webhook_trigger,
        python_code=python_code,
    )

    _stub_publish(monkeypatch)

    WebhookTriggerService().handle_webhook_trigger(path="wpath", payload={"a": 1})

    session = Session.objects.filter(graph=graph).order_by("-id").first()
    trigger = session.trigger

    assert trigger.trigger_type == SessionTrigger.TriggerType.WEBHOOK
    assert trigger.webhook_trigger_node_id == node.id
    assert trigger.node_name == "my_webhook"
    assert trigger.extra == {"path": "wpath", "config_id": None}
    assert session.entrypoint == f"my_webhook #{node.id}"


@pytest.mark.django_db
def test_telegram_trigger_creates_session_trigger_row_with_chat_id(
    default_org, monkeypatch
):
    graph = Graph.objects.create(name="tg", org=default_org)
    webhook_trigger = WebhookTrigger.objects.create(path="tgpath")
    node = TelegramTriggerNode.objects.create(
        graph=graph, node_name="my_telegram", webhook_trigger=webhook_trigger
    )

    _stub_publish(monkeypatch)

    payload = {"message": {"chat": {"id": 555}, "text": "hi"}}
    TelegramTriggerService().handle_telegram_trigger(url_path="tgpath", payload=payload)

    session = Session.objects.filter(graph=graph).order_by("-id").first()
    trigger = session.trigger

    assert trigger.trigger_type == SessionTrigger.TriggerType.TELEGRAM
    assert trigger.telegram_trigger_node_id == node.id
    assert trigger.node_name == "my_telegram"
    assert trigger.extra == {"chat_id": 555}
    assert session.entrypoint == f"my_telegram #{node.id}"


@pytest.mark.django_db
def test_telegram_trigger_extracts_chat_id_from_callback_query(
    default_org, monkeypatch
):
    graph = Graph.objects.create(name="tg2", org=default_org)
    webhook_trigger = WebhookTrigger.objects.create(path="tgpath2")
    TelegramTriggerNode.objects.create(
        graph=graph, node_name="cb_telegram", webhook_trigger=webhook_trigger
    )

    _stub_publish(monkeypatch)

    payload = {"callback_query": {"message": {"chat": {"id": 999}}}}
    TelegramTriggerService().handle_telegram_trigger(
        url_path="tgpath2", payload=payload
    )

    session = Session.objects.filter(graph=graph).order_by("-id").first()
    assert session.trigger.extra == {"chat_id": 999}


@pytest.mark.django_db
def test_telegram_trigger_omits_chat_id_when_absent(default_org, monkeypatch):
    graph = Graph.objects.create(name="tg3", org=default_org)
    webhook_trigger = WebhookTrigger.objects.create(path="tgpath3")
    TelegramTriggerNode.objects.create(
        graph=graph, node_name="no_chat_telegram", webhook_trigger=webhook_trigger
    )

    _stub_publish(monkeypatch)

    TelegramTriggerService().handle_telegram_trigger(
        url_path="tgpath3", payload={"unrelated": True}
    )

    session = Session.objects.filter(graph=graph).order_by("-id").first()
    assert session.trigger.extra == {}


@pytest.mark.django_db
def test_manual_run_session_creates_manual_trigger_with_resolved_graph_user(
    default_org, regular_user, monkeypatch
):
    from tables.models.rbac_models import OrganizationUser
    from tables.models.graph_models import GraphOrganizationUser

    graph = Graph.objects.create(name="manual", org=default_org)

    sm = _stub_publish(monkeypatch)

    session_id = sm.run_session(
        graph_id=graph.id,
        variables={},
        user=regular_user,
        trigger=TriggerSpec.manual(),
    )

    session = Session.objects.get(pk=session_id)
    membership = OrganizationUser.objects.get(user=regular_user, org=default_org)
    graph_user = GraphOrganizationUser.objects.get(
        graph=graph, organization_user=membership
    )

    assert session.trigger.trigger_type == SessionTrigger.TriggerType.MANUAL
    assert session.trigger.triggered_by_user_id == graph_user.id
    assert session.entrypoint is None


@pytest.mark.django_db
def test_create_session_is_atomic_no_orphan_session_on_trigger_failure(
    default_org, monkeypatch
):
    graph = Graph.objects.create(name="atomic", org=default_org)

    def _boom(*args, **kwargs):
        raise IntegrityError("forced failure")

    monkeypatch.setattr(SessionTrigger.objects, "create", _boom)

    with pytest.raises(IntegrityError):
        SessionManagerService().create_session(
            graph_id=graph.id,
            variables={},
            trigger=TriggerSpec.schedule(
                ScheduleTriggerNode.objects.create(graph=graph, node_name="n")
            ),
        )

    assert not Session.objects.filter(graph=graph).exists()
