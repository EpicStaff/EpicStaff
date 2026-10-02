import pytest

from tables.models.graph_models import (
    Graph,
    ScheduleTriggerNode,
    TelegramTriggerNode,
    WebhookTriggerNode,
)
from tables.models.python_models import PythonCode
from tables.models.session_models import Session, SessionPrincipal
from tables.models.webhook_models import WebhookTrigger
from rbac.identity.api_keys.principals import SystemServicePrincipal
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
    monkeypatch.setattr(
        sm, "create_session_data", lambda session, token_budget=None: _FakeSessionData()
    )
    monkeypatch.setattr(
        sm.redis_service,
        "publish_session_data",
        lambda *, session_data, org_id=None: 2,
    )
    return sm


@pytest.mark.django_db
def test_regular_member_run_creates_user_principal(
    default_org, regular_user, monkeypatch
):
    graph = Graph.objects.create(name="member-run", org=default_org)
    sm = _stub_publish(monkeypatch)

    session_id = sm.run_session(
        graph_id=graph.id,
        variables={},
        user=regular_user,
        trigger=TriggerSpec.manual(),
    )

    principal = Session.objects.get(pk=session_id).principal
    assert principal.kind == SessionPrincipal.ActionKind.USER
    assert principal.user_id == regular_user.id
    assert principal.email == regular_user.email
    assert principal.api_key_id is None


@pytest.mark.django_db
def test_superadmin_run_creates_user_principal(
    default_org, superadmin_user, monkeypatch
):
    # Superadmins have no org membership row, so graph_user stays None, but the
    # principal must still identify them by their real user account.
    graph = Graph.objects.create(name="superadmin-run", org=default_org)
    sm = _stub_publish(monkeypatch)

    session_id = sm.run_session(
        graph_id=graph.id,
        variables={},
        user=superadmin_user,
        trigger=TriggerSpec.manual(),
    )

    session = Session.objects.get(pk=session_id)
    principal = session.principal
    assert session.graph_user is None
    assert principal.kind == SessionPrincipal.ActionKind.USER
    assert principal.user_id == superadmin_user.id
    assert principal.email == superadmin_user.email


@pytest.mark.django_db
def test_system_api_key_run_creates_api_key_system_principal(
    default_org, env_api_key, monkeypatch
):
    graph = Graph.objects.create(name="system-key-run", org=default_org)
    _, key = env_api_key
    sm = _stub_publish(monkeypatch)

    session_id = sm.run_session(
        graph_id=graph.id,
        variables={},
        user=SystemServicePrincipal(),
        api_key=key,
        trigger=TriggerSpec.manual(),
    )

    principal = Session.objects.get(pk=session_id).principal
    assert principal.kind == SessionPrincipal.ActionKind.API_KEY_SYSTEM
    assert principal.api_key_id == key.id
    assert principal.user_id is None
    assert principal.email is None


@pytest.mark.django_db
def test_user_api_key_run_creates_api_key_user_principal(
    default_org, user_api_key, monkeypatch
):
    graph = Graph.objects.create(name="user-key-run", org=default_org)
    _, key = user_api_key
    owner = key.created_by
    sm = _stub_publish(monkeypatch)

    session_id = sm.run_session(
        graph_id=graph.id,
        variables={},
        user=owner,
        api_key=key,
        trigger=TriggerSpec.manual(),
    )

    principal = Session.objects.get(pk=session_id).principal
    assert principal.kind == SessionPrincipal.ActionKind.API_KEY_USER
    assert principal.user_id == owner.id
    assert principal.api_key_id == key.id
    assert principal.email == owner.email


@pytest.mark.django_db
def test_parent_flow_trigger_with_user_still_creates_user_principal(
    default_org, regular_user, monkeypatch
):
    # Actor resolution keys off user/api_key, not trigger type: a subflow run
    # (parent_flow trigger) started on behalf of an authenticated user is
    # still attributed to that user, not treated as automation.
    parent_graph = Graph.objects.create(name="parent", org=default_org)
    sm = _stub_publish(monkeypatch)
    parent_session_id = sm.run_session(
        graph_id=parent_graph.id,
        variables={},
        user=regular_user,
        trigger=TriggerSpec.manual(),
    )

    child_graph = Graph.objects.create(name="child", org=default_org)
    child_session_id = sm.run_session(
        graph_id=child_graph.id,
        variables={},
        user=regular_user,
        trigger=TriggerSpec.parent_flow(parent_session_id),
    )

    principal = Session.objects.get(pk=child_session_id).principal
    assert principal.kind == SessionPrincipal.ActionKind.USER
    assert principal.user_id == regular_user.id


@pytest.mark.django_db
def test_schedule_trigger_creates_trigger_principal(default_org, monkeypatch):
    graph = Graph.objects.create(name="sched-principal", org=default_org)
    node = ScheduleTriggerNode.objects.create(graph=graph, node_name="my_schedule")
    _stub_publish(monkeypatch)

    ScheduleTriggerService()._start_session(node)

    session = Session.objects.filter(graph=graph).order_by("-id").first()
    principal = session.principal
    assert principal.kind == SessionPrincipal.ActionKind.TRIGGER
    assert principal.user_id is None
    assert principal.api_key_id is None
    assert principal.email is None


@pytest.mark.django_db
def test_webhook_trigger_creates_trigger_principal(default_org, monkeypatch):
    graph = Graph.objects.create(name="wh-principal", org=default_org)
    webhook_trigger = WebhookTrigger.objects.create(
        path="wpath-principal", org=default_org
    )
    python_code = PythonCode.objects.create(code="def main(): return None")
    WebhookTriggerNode.objects.create(
        graph=graph,
        node_name="my_webhook",
        webhook_trigger=webhook_trigger,
        python_code=python_code,
    )
    _stub_publish(monkeypatch)

    WebhookTriggerService().handle_webhook_trigger(
        path="wpath-principal", payload={"a": 1}
    )

    session = Session.objects.filter(graph=graph).order_by("-id").first()
    principal = session.principal
    assert principal.kind == SessionPrincipal.ActionKind.TRIGGER
    assert principal.user_id is None
    assert principal.api_key_id is None


@pytest.mark.django_db
def test_telegram_trigger_creates_trigger_principal(default_org, monkeypatch):
    graph = Graph.objects.create(name="tg-principal", org=default_org)
    webhook_trigger = WebhookTrigger.objects.create(
        path="tgpath-principal", org=default_org
    )
    TelegramTriggerNode.objects.create(
        graph=graph, node_name="my_telegram", webhook_trigger=webhook_trigger
    )
    _stub_publish(monkeypatch)

    payload = {"message": {"chat": {"id": 555}, "text": "hi"}}
    TelegramTriggerService().handle_telegram_trigger(
        path="tgpath-principal", payload=payload
    )

    session = Session.objects.filter(graph=graph).order_by("-id").first()
    principal = session.principal
    assert principal.kind == SessionPrincipal.ActionKind.TRIGGER
    assert principal.user_id is None
    assert principal.api_key_id is None
