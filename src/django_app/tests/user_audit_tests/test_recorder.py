import pytest
from django.contrib.auth.models import AnonymousUser
from django.db import connection, transaction
from django.test import RequestFactory
from loguru import logger
from rest_framework.request import Request

from plugins.identity.principals import PluginServiceAccountPrincipal
from plugins.ownership.request_scope import request_scope
from rbac.access.org_context import cache_active_org_id
from rbac.identity.authentication import JwtOrApiKeyAuthentication
from rbac.models import OrganizationConfig, OrganizationUser
from src.shared.models import UserAction
from agents.models import AgentDefinition, Surface
from tables.models import Graph, PythonCode, PythonNode, SourceCollection, WebhookTrigger
from user_audit import recorder
from user_audit.actor import Actor, actor_from_request
from user_audit.context import user_action_context
from user_audit.recorder import record_for_user_orgs, record_user_action
from user_audit.targets import TargetDescription, describe

from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403


@pytest.fixture
def flow(acme):
    return Graph.objects.create(name="Billing flow", org=acme)


@pytest.fixture
def python_node(flow):
    python_code = PythonCode.objects.create(code="def main():\n    return 1\n", entrypoint="main")
    return PythonNode.objects.create(
        graph=flow, python_code=python_code, node_name="Fetch invoices"
    )


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
@pytest.mark.parametrize("agent_specific", [True, False])
def test_record_names_a_surfaces_owner_agent_as_its_parent(
    agent_specific, acme, admin_acme, sent_events, django_capture_on_commit_callbacks
):
    agent = AgentDefinition.objects.create(org=acme, name="Researcher")
    surface = Surface.objects.create(
        org=acme, name="notes", owner_agent=agent if agent_specific else None
    )

    with user_action_context(request_as(admin_acme)):
        with django_capture_on_commit_callbacks(execute=True):
            record_user_action(action=UserAction.UPDATED, org_id=acme.id, target=surface)

    [event] = sent_events
    expected_parent = ("agent", str(agent.id), "Researcher") if agent_specific else (None, None, None)
    assert (event.parent_type, event.parent_id, event.parent_name) == expected_parent


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
def test_record_is_noop_without_context(
    acme, flow, sent_events, django_capture_on_commit_callbacks
):
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

    assert actor == Actor(
        user_id=regular_user.id, email="user@example.com", api_key_name="user-key"
    )


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
    assert len({event.number for event in sent_events}) == 2


@pytest.mark.django_db
def test_describe_labels_graph_as_flow(flow):
    assert describe(flow) == TargetDescription(type="flow", id=str(flow.id), name="Billing flow")


@pytest.mark.django_db
def test_describe_uses_verbose_name_and_node_name(python_node):
    assert describe(python_node) == TargetDescription(
        type="python node", id=str(python_node.id), name="Fetch invoices"
    )


@pytest.mark.django_db
def test_describe_names_a_collection_and_a_webhook_trigger_by_their_own_fields(acme):
    collection = SourceCollection.objects.create(org=acme, collection_name="Invoices")
    trigger = WebhookTrigger.objects.create(org=acme, path="invoice-paid")

    assert describe(collection).name == "Invoices"
    assert describe(trigger).name == "invoice-paid"


def test_cache_active_org_id_sets_underlying_http_request():
    http_request = RequestFactory().get("/api/graphs/")
    drf_request = Request(http_request)

    cache_active_org_id(drf_request, 7)

    assert drf_request._rbac_active_org_id == 7
    # The middleware holds the HttpRequest, so it must see the org the view resolved.
    assert http_request._rbac_active_org_id == 7


@pytest.mark.django_db
def test_failing_sender_does_not_raise_from_the_committing_code(
    acme, admin_acme, flow, monkeypatch, settings, django_capture_on_commit_callbacks
):
    settings.USER_AUDIT_TRAIL_ENABLED = True

    def broken_sender_factory():
        raise RuntimeError("sender unavailable")

    monkeypatch.setattr(recorder, "get_user_audit_sender", broken_sender_factory)

    with user_action_context(request_as(admin_acme)):
        with django_capture_on_commit_callbacks(execute=True) as callbacks:
            record_user_action(action=UserAction.UPDATED, org_id=acme.id, target=flow)

    assert len(callbacks) == 1


@pytest.mark.django_db
def test_record_for_user_orgs_queries_nothing_when_switch_off(
    admin_acme, sent_events, settings, django_assert_num_queries
):
    settings.USER_AUDIT_TRAIL_ENABLED = False
    actor = Actor(user_id=admin_acme.id, email=admin_acme.email, api_key_name=None)

    with django_assert_num_queries(0):
        record_for_user_orgs(action=UserAction.SIGNED_IN, actor=actor)

    assert sent_events == []


@pytest.mark.django_db
def test_record_for_user_orgs_skips_inactive_orgs(
    acme, beta, admin_acme, role_member, sent_events, django_capture_on_commit_callbacks
):
    OrganizationUser.objects.create(user=admin_acme, org=beta, role=role_member)
    beta.is_active = False
    beta.save(update_fields=["is_active"])
    actor = Actor(user_id=admin_acme.id, email=admin_acme.email, api_key_name=None)

    with django_capture_on_commit_callbacks(execute=True):
        record_for_user_orgs(action=UserAction.SIGNED_IN, actor=actor)

    assert [event.org_id for event in sent_events] == [acme.id]


@pytest.mark.django_db
def test_failed_retention_read_leaves_the_callers_transaction_usable(
    acme, admin_acme, flow, sent_events, monkeypatch
):
    def failing_retention_read(org_id, data_type):
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM table_that_does_not_exist")

    monkeypatch.setattr(recorder, "effective_retention_days_for_org", failing_retention_read)

    with user_action_context(request_as(admin_acme)), transaction.atomic():
        record_user_action(action=UserAction.UPDATED, org_id=acme.id, target=flow)
        assert Graph.objects.filter(pk=flow.pk).exists()


@pytest.mark.django_db
def test_retention_is_read_once_per_org_per_request(
    acme, beta, admin_acme, flow, sent_events, django_capture_on_commit_callbacks, monkeypatch
):
    reads = []
    real_read = recorder.effective_retention_days_for_org

    def counting_read(org_id, data_type):
        reads.append(org_id)
        return real_read(org_id, data_type)

    monkeypatch.setattr(recorder, "effective_retention_days_for_org", counting_read)

    with user_action_context(request_as(admin_acme)):
        with django_capture_on_commit_callbacks(execute=True):
            for org in (acme, acme, beta):
                record_user_action(action=UserAction.UPDATED, org_id=org.id, target=flow)

    assert sorted(reads) == sorted([acme.id, beta.id])
    assert len(sent_events) == 3


@pytest.mark.django_db
def test_records_get_increasing_numbers(
    acme, admin_acme, flow, sent_events, django_capture_on_commit_callbacks
):
    with user_action_context(request_as(admin_acme)):
        with django_capture_on_commit_callbacks(execute=True):
            record_user_action(action=UserAction.CREATED, org_id=acme.id, target=flow)
            record_user_action(action=UserAction.UPDATED, org_id=acme.id, target=flow)

    first, second = sent_events
    assert isinstance(first.number, int)
    assert second.number > first.number


@pytest.mark.django_db
def test_failed_record_number_read_is_logged_and_leaves_the_callers_transaction_usable(
    acme, admin_acme, flow, sent_events, django_capture_on_commit_callbacks
):
    errors = []
    sink_id = logger.add(lambda message: errors.append(str(message)), level="ERROR")
    try:
        with user_action_context(request_as(admin_acme)), transaction.atomic():
            # Dropped inside the test's transaction, so it is back for the next test.
            with connection.cursor() as cursor:
                cursor.execute("DROP SEQUENCE user_action_record_number_seq")
            with django_capture_on_commit_callbacks(execute=True):
                record_user_action(action=UserAction.UPDATED, org_id=acme.id, target=flow)
            assert Graph.objects.filter(pk=flow.pk).exists()
    finally:
        logger.remove(sink_id)

    assert sent_events == []
    assert any("Failed to record user action updated" in error for error in errors)
