import pytest
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory
from rest_framework.request import Request

from plugins.identity.principals import PluginServiceAccountPrincipal
from plugins.ownership.request_scope import request_scope
from rbac.access.org_context import cache_active_org_id
from rbac.identity.authentication import JwtOrApiKeyAuthentication
from rbac.models import OrganizationConfig, OrganizationUser
from src.shared.models import UserAction
from tables.models import Graph, PythonCode, PythonNode
from user_audit import recorder
from user_audit.actor import Actor, actor_from_request
from user_audit.context import user_action_context
from user_audit.recorder import record_for_user_orgs, record_user_action
from user_audit.targets import TargetDescription, describe

from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403


class RecordingSender:
    def __init__(self):
        self.events = []

    def send(self, events):
        self.events.extend(events)


@pytest.fixture
def sent_events(monkeypatch, settings):
    settings.USER_AUDIT_TRAIL_ENABLED = True
    sender = RecordingSender()
    monkeypatch.setattr(recorder, "get_user_audit_sender", lambda: sender)
    return sender.events


@pytest.fixture
def flow(acme):
    return Graph.objects.create(name="Billing flow", org=acme)


@pytest.fixture
def python_node(flow):
    python_code = PythonCode.objects.create(code="def main():\n    return 1\n", entrypoint="main")
    return PythonNode.objects.create(graph=flow, python_code=python_code, node_name="Fetch invoices")


def request_as(user):
    request = RequestFactory().get("/api/graphs/")
    request.user = user
    return request


def authenticated_http_request(raw_key):
    """An HttpRequest after DRF authenticated it, as the middleware's context holds it."""
    http_request = RequestFactory().get("/api/graphs/", HTTP_X_API_KEY=raw_key)
    drf_request = Request(http_request, authenticators=[JwtOrApiKeyAuthentication()])
    drf_request.user  # noqa: B018 - reading it runs authentication.
    return http_request


@pytest.mark.django_db
def test_record_sends_event_after_commit_only(
    acme, admin_acme, flow, python_node, sent_events, django_capture_on_commit_callbacks
):
    OrganizationConfig.objects.create(org=acme, retention_audit_days=90)

    with user_action_context(request_as(admin_acme)) as context:
        with django_capture_on_commit_callbacks(execute=True):
            record_user_action(
                action=UserAction.UPDATED, org_id=acme.id, target=python_node, parent=flow
            )
            assert sent_events == []

    assert context.recorded is True
    [event] = sent_events
    assert event.action == "updated"
    assert event.org_id == acme.id
    assert event.retention_days == 90
    assert (event.actor_user_id, event.actor_email, event.actor_api_key_name) == (
        admin_acme.id,
        "admin-acme-xorg@example.com",
        None,
    )
    assert (event.target_type, event.target_id, event.target_name) == (
        "python node",
        str(python_node.id),
        "Fetch invoices",
    )
    assert (event.parent_type, event.parent_id, event.parent_name) == (
        "flow",
        str(flow.id),
        "Billing flow",
    )


@pytest.mark.django_db
def test_record_is_noop_when_switch_off(
    acme, admin_acme, flow, sent_events, settings, django_capture_on_commit_callbacks
):
    settings.USER_AUDIT_TRAIL_ENABLED = False

    with user_action_context(request_as(admin_acme)) as context:
        with django_capture_on_commit_callbacks(execute=True):
            record_user_action(action=UserAction.CREATED, org_id=acme.id, target=flow)

    assert sent_events == []
    assert context.recorded is False


@pytest.mark.django_db
def test_record_is_noop_without_context(acme, flow, sent_events, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        record_user_action(action=UserAction.CREATED, org_id=acme.id, target=flow)

    assert sent_events == []


@pytest.mark.django_db
def test_record_is_noop_for_anonymous_request(
    acme, flow, sent_events, django_capture_on_commit_callbacks
):
    with user_action_context(request_as(AnonymousUser())) as context:
        with django_capture_on_commit_callbacks(execute=True):
            record_user_action(action=UserAction.CREATED, org_id=acme.id, target=flow)

    assert sent_events == []
    assert context.recorded is False


@pytest.mark.django_db
def test_record_skips_plugin_principal(
    acme, admin_acme, flow, sent_events, django_capture_on_commit_callbacks
):
    principal = PluginServiceAccountPrincipal(
        service_account_id=1,
        grant_id=1,
        pinned_org_id=acme.id,
        plugin_identifier="acme.plugin",
        plugin_name="Acme plugin",
        package=None,
        requests_per_minute=60,
        development_key=False,
        person=admin_acme,
    )
    # The session user is still on the HttpRequest; the plugin principal must win.
    with request_scope() as scope, user_action_context(request_as(admin_acme)):
        scope.principal = principal
        with django_capture_on_commit_callbacks(execute=True):
            record_user_action(action=UserAction.CREATED, org_id=acme.id, target=flow)

    assert sent_events == []


@pytest.mark.django_db
def test_record_uses_explicit_target_description_and_route(
    acme, admin_acme, sent_events, django_capture_on_commit_callbacks
):
    with user_action_context(request_as(admin_acme)):
        with django_capture_on_commit_callbacks(execute=True):
            record_user_action(
                action="copy",
                org_id=acme.id,
                target_description=TargetDescription(type="flow", id="42", name="Gone flow"),
                previous_name="Old name",
                route="POST api/graphs/<int:pk>/copy/",
            )

    [event] = sent_events
    assert (event.target_type, event.target_id, event.target_name) == ("flow", "42", "Gone flow")
    assert event.previous_name == "Old name"
    assert event.route == "POST api/graphs/<int:pk>/copy/"
    assert event.parent_type is None


@pytest.mark.django_db
def test_actor_for_personal_api_key_is_owner_with_key_name(regular_user, user_api_key):
    raw_key, _ = user_api_key

    actor = actor_from_request(authenticated_http_request(raw_key))

    assert actor == Actor(user_id=regular_user.id, email="user@example.com", api_key_name="user-key")


@pytest.mark.django_db
def test_actor_for_system_key_has_key_name_and_no_user(env_api_key):
    raw_key, _ = env_api_key

    actor = actor_from_request(authenticated_http_request(raw_key))

    assert actor == Actor(user_id=None, email="", api_key_name="env-system")


@pytest.mark.django_db
def test_record_for_user_orgs_writes_one_event_per_membership(
    acme, beta, admin_acme, role_member, sent_events, django_capture_on_commit_callbacks
):
    OrganizationUser.objects.create(user=admin_acme, org=beta, role=role_member)
    actor = Actor(user_id=admin_acme.id, email=admin_acme.email, api_key_name=None)

    # No request context: sign-in records name the actor explicitly.
    with django_capture_on_commit_callbacks(execute=True):
        record_for_user_orgs(action=UserAction.SIGNED_IN, actor=actor)

    assert sorted(event.org_id for event in sent_events) == sorted([acme.id, beta.id])
    assert {event.action for event in sent_events} == {"signed_in"}
    assert {event.actor_user_id for event in sent_events} == {admin_acme.id}


@pytest.mark.django_db
def test_describe_labels_graph_as_flow(flow):
    assert describe(flow) == TargetDescription(type="flow", id=str(flow.id), name="Billing flow")


@pytest.mark.django_db
def test_describe_uses_verbose_name_and_node_name(python_node):
    assert describe(python_node) == TargetDescription(
        type="python node", id=str(python_node.id), name="Fetch invoices"
    )


def test_cache_active_org_id_sets_underlying_http_request():
    http_request = RequestFactory().get("/api/graphs/")
    drf_request = Request(http_request)

    cache_active_org_id(drf_request, 7)

    assert drf_request._rbac_active_org_id == 7
    # The middleware holds the HttpRequest, so it must see the org the view resolved.
    assert http_request._rbac_active_org_id == 7
