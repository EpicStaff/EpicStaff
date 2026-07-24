import pytest

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


class _FakeGraphDump:
    def model_dump(self, mode=None):
        return {}


class _FakeSessionData:
    graph = _FakeGraphDump()


def _stub_publish(monkeypatch):
    """Stub the run_session tail (SessionData build + Redis publish)."""
    sm = SessionManagerService()
    monkeypatch.setattr(sm, "create_session_data", lambda session: _FakeSessionData())
    monkeypatch.setattr(
        sm.redis_service, "publish_session_data", lambda session_data: 2
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
    trigger = WebhookTrigger.objects.create(path="tgpath")
    TelegramTriggerNode.objects.create(
        graph=graph, node_name="tg_node", webhook_trigger=trigger
    )

    _stub_publish(monkeypatch)

    TelegramTriggerService().handle_telegram_trigger(
        url_path="tgpath", payload={"m": 1}
    )

    session = Session.objects.filter(graph=graph).order_by("-id").first()
    assert session is not None
    # org value merged in (the bug discarded this merge) ...
    assert session.variables.get("counter") == 5
    # ... and the trigger payload preserved
    assert session.variables.get("telegram_payload") == {"m": 1}
