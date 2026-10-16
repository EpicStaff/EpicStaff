import pytest

from src.shared.models import GraphData, SessionData
from tables.models import PythonCode
from tables.models.graph_models import Graph, TelegramTriggerNode, WebhookTriggerNode
from tables.models.session_models import Session
from tables.models.webhook_models import WebhookTrigger
from tables.services.session_manager_service import SessionManagerService
from tables.services.telegram_trigger_service import TelegramTriggerService
from tables.services.webhook_trigger_service import WebhookTriggerService


def _empty_session_data(session, **kwargs):
    graph = GraphData(name="g", entrypoint="__end__", end_node=None)
    return SessionData(id=session.id, org_id=session.graph.org_id, graph=graph)


@pytest.fixture
def first_publish_fails(monkeypatch):
    """The first run on the path fails to publish; every later run is received."""
    session_manager = SessionManagerService()
    monkeypatch.setattr(session_manager, "create_session_data", _empty_session_data)
    publish_calls = []

    def publish(*, session_data, org_id, storage_credentials=None):
        publish_calls.append(org_id)
        if len(publish_calls) == 1:
            raise RuntimeError("redis is down")
        return 1

    monkeypatch.setattr(session_manager.redis_service, "publish_session_data", publish)


@pytest.fixture
def no_registration_side_effects(monkeypatch):
    monkeypatch.setattr(WebhookTriggerService, "register_webhooks", lambda self: True)
    monkeypatch.setattr(
        TelegramTriggerService,
        "register_telegram_trigger",
        lambda self, telegram_trigger_instance=None, **kwargs: None,
    )


def _statuses(graphs):
    return sorted(
        Session.objects.filter(graph__in=graphs).values_list("status", flat=True)
    )


@pytest.mark.django_db
@pytest.mark.usefixtures("no_registration_side_effects", "first_publish_fails")
def test_webhook_trigger_starts_remaining_flows_after_one_fails(default_org):
    webhook_trigger = WebhookTrigger.objects.create(path="shared-path", org=default_org)
    graphs = [
        Graph.objects.create(name=f"webhook flow {index}", org=default_org)
        for index in range(2)
    ]
    for graph in graphs:
        WebhookTriggerNode.objects.create(
            graph=graph,
            node_name="webhook",
            webhook_trigger=webhook_trigger,
            python_code=PythonCode.objects.create(code="def main(): return None"),
        )

    WebhookTriggerService().handle_webhook_trigger(path="shared-path", payload={"a": 1})

    assert _statuses(graphs) == [Session.SessionStatus.ERROR, Session.SessionStatus.PENDING]


@pytest.mark.django_db
@pytest.mark.usefixtures("no_registration_side_effects", "first_publish_fails")
def test_telegram_trigger_starts_remaining_flows_after_one_fails(default_org):
    webhook_trigger = WebhookTrigger.objects.create(path="shared-tg-path", org=default_org)
    graphs = [
        Graph.objects.create(name=f"telegram flow {index}", org=default_org)
        for index in range(2)
    ]
    for graph in graphs:
        TelegramTriggerNode.objects.create(
            graph=graph, node_name="telegram", webhook_trigger=webhook_trigger
        )

    TelegramTriggerService().handle_telegram_trigger(path="shared-tg-path", payload={"m": 1})

    assert _statuses(graphs) == [Session.SessionStatus.ERROR, Session.SessionStatus.PENDING]
