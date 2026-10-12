import pytest

from tables.models.graph_models import (
    Graph,
    GraphOrganization,
    GraphOrganizationUser,
    StartNode,
)
from tables.models.session_models import Session
from tables.serializers.serializers import RunSessionSerializer
from rbac.models import OrganizationUser
from tables.services.session_manager_service import SessionManagerService
from tables.services.trigger_spec import TriggerSpec
from tests.services_tests.session_trigger_creation_test import _stub_publish


@pytest.mark.django_db
def test_create_session_uses_passed_graph_user(default_org, regular_user):
    graph = Graph.objects.create(name="cs", org=default_org)
    StartNode.objects.create(graph=graph, variables={"variables": {}})
    membership = OrganizationUser.objects.get(user=regular_user, org=default_org)
    gu = GraphOrganizationUser.objects.create(graph=graph, organization_user=membership)

    session = SessionManagerService().create_session(
        graph_id=graph.id, variables={}, graph_user=gu, trigger=TriggerSpec.manual(gu)
    )
    assert session.graph_user_id == gu.id


def test_run_session_no_longer_has_choose_variables():
    assert not hasattr(SessionManagerService, "choose_variables")


CHAT_RUN_VARIABLES = {
    "chat_history": [{"role": "user", "content": "Yes", "action": {"id": "yes"}}],
    "user_message": "",
    "action": {"type": "button", "id": "refund"},
    "chat_extra_data": {"plan": "pro"},
    "chat_user_id": "customer-42",
}
CHAT_DECLARED = {"chat_history": [], "user_message": ""}


def _run_chat_session(monkeypatch, org, user, start_variables, variables):
    """Start a run the way the chat service does: run-session serializer, then run_session."""
    graph = Graph.objects.create(name=f"chat-{Graph.objects.count()}", org=org)
    StartNode.objects.create(graph=graph, variables={"variables": start_variables})
    serializer = RunSessionSerializer(data={"graph_id": graph.id, "variables": variables})
    assert serializer.is_valid(), serializer.errors
    session_id = _stub_publish(monkeypatch).run_session(
        graph_id=graph.id,
        variables=serializer.validated_data["variables"],
        user=user,
        trigger=TriggerSpec.manual(),
    )
    return Session.objects.get(pk=session_id)


# The chat service sends these five keys on every run while a chat flow must declare only the
# first two, so undeclared run variables have to reach Session.variables unchanged.
@pytest.mark.django_db
def test_run_variables_the_start_node_does_not_declare_reach_the_session(
    monkeypatch, default_org, regular_user
):
    session = _run_chat_session(
        monkeypatch, default_org, regular_user, CHAT_DECLARED, CHAT_RUN_VARIABLES
    )
    assert session.variables == CHAT_RUN_VARIABLES


@pytest.mark.django_db
def test_undeclared_run_variables_survive_the_org_persistent_variables_merge(
    monkeypatch, default_org, regular_user
):
    graph = Graph.objects.create(
        name="chat-persistent", org=default_org, enable_persistent_variables=True
    )
    GraphOrganization.objects.create(graph=graph, persistent_variables={"visits": 3})
    StartNode.objects.create(graph=graph, variables={"variables": CHAT_DECLARED})
    session_id = _stub_publish(monkeypatch).run_session(
        graph_id=graph.id,
        variables=dict(CHAT_RUN_VARIABLES),
        user=regular_user,
        trigger=TriggerSpec.manual(),
    )
    assert Session.objects.get(pk=session_id).variables == {
        **CHAT_RUN_VARIABLES,
        "visits": 3,
    }


@pytest.mark.django_db
def test_a_declared_dict_default_is_deep_merged_and_a_null_run_variable_replaces_it(
    monkeypatch, default_org, regular_user
):
    """Why the chat service sends a cleared chat_extra_data as null, never {}."""
    declared = {**CHAT_DECLARED, "chat_extra_data": {"plan": "free", "locale": "en"}}
    merged = _run_chat_session(
        monkeypatch, default_org, regular_user, declared, CHAT_RUN_VARIABLES
    )
    assert merged.variables["chat_extra_data"] == {"plan": "pro", "locale": "en"}
    emptied = _run_chat_session(
        monkeypatch,
        default_org,
        regular_user,
        declared,
        {**CHAT_RUN_VARIABLES, "chat_extra_data": {}},
    )
    assert emptied.variables["chat_extra_data"] == {"plan": "free", "locale": "en"}
    cleared = _run_chat_session(
        monkeypatch,
        default_org,
        regular_user,
        declared,
        {**CHAT_RUN_VARIABLES, "chat_extra_data": None},
    )
    assert cleared.variables["chat_extra_data"] is None
