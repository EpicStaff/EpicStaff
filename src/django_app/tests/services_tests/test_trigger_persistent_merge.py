import pytest
from src.shared.models import GraphData, SessionData

from tables.models.graph_models import (
    Graph,
    GraphOrganization,
    StartNode,
    TelegramTriggerNode,
)
from tables.models.session_models import Session
from tables.models.webhook_models import WebhookTrigger
from tables.services.session_manager_service import SessionManagerService
from tables.services.telegram_trigger_service import TelegramTriggerService
from tables.services.webhook_trigger_service import WebhookTriggerService


def _empty_session_data() -> SessionData:
    """Real session data with an empty graph: only the session's own records are under
    test, and a hand-made stand-in breaks as soon as production reads a new field."""
    return SessionData(id=1, org_id=1, graph=GraphData(name="stub", entrypoint="__end__", end_node=None))


def _stub_publish(monkeypatch):
    """Stub the run_session tail (SessionData build + Redis publish)."""
    sm = SessionManagerService()
    monkeypatch.setattr(
        sm, "create_session_data", lambda session, **kwargs: _empty_session_data()
    )
    monkeypatch.setattr(
        sm.redis_service, "publish_session_data", lambda session_data, **kwargs: 2
    )
    return sm


@pytest.mark.django_db
def test_telegram_trigger_merges_org_and_keeps_payload(default_org, monkeypatch):
    graph = Graph.objects.create(
        name="tg", org=default_org, enable_persistent_variables=True
    )
    StartNode.objects.create(
        graph=graph,
        variables={
            "variables": {"counter": 0},
            "persistent_variables": {"organization": ["counter"], "user": []},
        },
    )
    GraphOrganization.objects.create(graph=graph, persistent_variables={"counter": 5})
    trigger = WebhookTrigger.objects.create(path="tgpath", org=default_org)

    # `TelegramTriggerNode.objects.create()` fires
    # `telegram_signals.telegram_trigger_post_save_handler`, which otherwise
    # makes a REAL `WebhookTriggerService().register_webhooks()` Redis
    # publish and a REAL outbound Telegram API call via
    # `TelegramTriggerService().register_telegram_trigger()`. Stub both
    # before creating the node -- this test only cares about persistent
    # variable merging.
    monkeypatch.setattr(WebhookTriggerService, "register_webhooks", lambda self: True)
    monkeypatch.setattr(
        TelegramTriggerService,
        "register_telegram_trigger",
        lambda self, telegram_trigger_instance=None, **kwargs: None,
    )

    TelegramTriggerNode.objects.create(
        graph=graph, node_name="tg_node", webhook_trigger=trigger
    )

    _stub_publish(monkeypatch)

    TelegramTriggerService().handle_telegram_trigger(path="tgpath", payload={"m": 1})

    session = Session.objects.filter(graph=graph).order_by("-id").first()
    assert session is not None
    # org value merged in (the bug discarded this merge) ...
    assert session.variables.get("counter") == 5
    # ... and the trigger payload preserved
    assert session.variables.get("telegram_payload") == {"m": 1}
