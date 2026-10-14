import pytest

from storage_credentials.services.session_credential_service import (
    session_credential_service,
)
from tables.models import PythonCode
from tables.models.graph_models import (
    Graph,
    GraphOrganization,
    StartNode,
    TelegramTriggerNode,
    WebhookTriggerNode,
)
from tables.models.session_models import Session
from tables.models.webhook_models import WebhookTrigger
from tables.services.session_manager_service import SessionManagerService
from tables.services.telegram_trigger_service import TelegramTriggerService
from tables.services.webhook_trigger_service import WebhookTriggerService


class _FakeGraphDump:
    def model_dump(self, mode=None):
        return {}


class _FakeSessionData:
    graph = _FakeGraphDump()


def _stub_publish(monkeypatch):
    """Stub the run_session tail (SessionData build + Redis publish)."""
    sm = SessionManagerService()
    monkeypatch.setattr(
        sm, "create_session_data", lambda session, **kwargs: _FakeSessionData()
    )
    monkeypatch.setattr(
        sm.redis_service, "publish_session_data", lambda session_data, **kwargs: 2
    )
    monkeypatch.setattr(
        session_credential_service, "issue_for_session", lambda **kwargs: None
    )
    return sm


def _stub_telegram_registration(monkeypatch):
    # `TelegramTriggerNode.objects.create()` fires
    # `telegram_signals.telegram_trigger_post_save_handler`, which otherwise
    # makes a REAL `WebhookTriggerService().register_webhooks()` Redis
    # publish and a REAL outbound Telegram API call via
    # `TelegramTriggerService().register_telegram_trigger()`. Stub both
    # before creating the node -- these tests only care about persistent
    # variable merging.
    monkeypatch.setattr(WebhookTriggerService, "register_webhooks", lambda self: True)
    monkeypatch.setattr(
        TelegramTriggerService,
        "register_telegram_trigger",
        lambda self, telegram_trigger_instance=None, **kwargs: None,
    )


def _graph_declaring_org_path_under(default_org, payload_key):
    graph = Graph.objects.create(
        name=payload_key, org=default_org, enable_persistent_variables=True
    )
    StartNode.objects.create(
        graph=graph,
        variables={
            "variables": {payload_key: {"last_event": ""}},
            "persistent_variables": {
                "organization": [f"{payload_key}.last_event"],
                "user": [],
            },
        },
    )
    GraphOrganization.objects.create(
        graph=graph, persistent_variables={payload_key: {"last_event": "old"}}
    )
    return graph


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
    _stub_telegram_registration(monkeypatch)

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


@pytest.mark.django_db
def test_telegram_trigger_payload_sets_org_path_declared_under_its_key(
    default_org, monkeypatch
):
    graph = _graph_declaring_org_path_under(default_org, "telegram_payload")
    _stub_telegram_registration(monkeypatch)
    TelegramTriggerNode.objects.create(
        graph=graph,
        node_name="tg_node",
        webhook_trigger=WebhookTrigger.objects.create(path="tgpath", org=default_org),
    )
    _stub_publish(monkeypatch)

    TelegramTriggerService().handle_telegram_trigger(
        path="tgpath", payload={"last_event": "new"}
    )

    session = Session.objects.get(graph=graph)
    assert session.variables["telegram_payload"] == {"last_event": "new"}


@pytest.mark.django_db
def test_webhook_trigger_payload_sets_org_path_declared_under_its_key(
    default_org, monkeypatch
):
    graph = _graph_declaring_org_path_under(default_org, "trigger_payload")
    WebhookTriggerNode.objects.create(
        graph=graph,
        node_name="wh_node",
        python_code=PythonCode.objects.create(code="def main(**kwargs): ..."),
        webhook_trigger=WebhookTrigger.objects.create(path="whpath", org=default_org),
    )
    _stub_publish(monkeypatch)

    WebhookTriggerService().handle_webhook_trigger(
        path="whpath", payload={"last_event": "new"}
    )

    session = Session.objects.get(graph=graph)
    assert session.variables["trigger_payload"] == {"last_event": "new"}
