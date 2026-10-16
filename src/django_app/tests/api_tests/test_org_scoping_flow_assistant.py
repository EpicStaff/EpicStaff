"""Org scoping for the Flow Assistant endpoints (/api/flow-assistants/<graph_id>/...).

These were once IsAuthenticated-only with an unscoped graph lookup, so any user could
read or patch another org's assistant, attach a cross-org LLMConfig, and start a
conversation row against another org's graph. Now: org context + FLOWS verb gate +
row scope (another org's graph is a 404, before any conversation lookup) + an
org-scoped llm_config.
"""

import pytest
from rest_framework.test import APIClient

from tables.models import Graph
from tables.models.flow_assistant_models import FlowAssistantConversation
from tables.models.llm_models import LLMConfig
from rbac.models import Organization, OrganizationUser, Role
from rbac.models.enums import BuiltInRole

pytestmark = pytest.mark.django_db


@pytest.fixture
def org_a(db):
    return Organization.objects.create(name="Org A")


@pytest.fixture
def org_b(db):
    return Organization.objects.create(name="Org B")


def _client(django_user_model, org, role_name):
    user = django_user_model.objects.create_user(email=f"{role_name}@example.com", password="StrongPass123!")
    OrganizationUser.objects.create(
        user=user, org=org, role=Role.objects.get(name=role_name, is_built_in=True, org__isnull=True)
    )
    client = APIClient()
    client.force_authenticate(user=user)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
    return client


@pytest.fixture
def admin_a(db, django_user_model, org_a):
    return _client(django_user_model, org_a, BuiltInRole.ORG_ADMIN)


@pytest.fixture
def viewer_a(db, django_user_model, org_a):
    return _client(django_user_model, org_a, BuiltInRole.VIEWER)


def _graph(org):
    return Graph.objects.create(name="g", metadata={"nodes": [], "edges": []}, org=org)


ROUTES = {
    "config-get": ("get", "/api/flow-assistants/{graph}/", {}),
    "config-patch": ("patch", "/api/flow-assistants/{graph}/", {}),
    "conversations-list": ("get", "/api/flow-assistants/{graph}/conversations/", {}),
    "conversation-start": ("post", "/api/flow-assistants/{graph}/conversations/", {}),
    # The graph check runs before the conversation lookup, so a bogus id still 404s on the graph.
    "conversation-get": ("get", "/api/flow-assistants/{graph}/conversations/999999/", {}),
    "conversation-delete": ("delete", "/api/flow-assistants/{graph}/conversations/999999/", {}),
    "message-send": ("post", "/api/flow-assistants/{graph}/conversations/999999/messages/", {"message": "hi"}),
}


@pytest.mark.parametrize("route", list(ROUTES))
def test_another_orgs_graph_is_404_and_writes_nothing(admin_a, org_b, route):
    method, url, body = ROUTES[route]
    graph_b = _graph(org_b)

    resp = getattr(admin_a, method)(url.format(graph=graph_b.id), body, format="json")

    assert resp.status_code == 404, resp.data
    assert not FlowAssistantConversation.objects.filter(flow_assistant__graph_id=graph_b.id).exists()


@pytest.mark.parametrize(
    ("client", "method", "url", "expected_status"),
    [
        ("admin_a", "get", "/api/flow-assistants/{graph}/", 200),
        ("admin_a", "get", "/api/flow-assistants/{graph}/conversations/", 200),
        # A Viewer has FLOWS READ: it may read the config and use the assistant...
        ("viewer_a", "get", "/api/flow-assistants/{graph}/", 200),
        ("viewer_a", "post", "/api/flow-assistants/{graph}/conversations/", 201),
        # ...but not change the config (no FLOWS UPDATE).
        ("viewer_a", "patch", "/api/flow-assistants/{graph}/", 403),
    ],
)
def test_own_graph_follows_the_flows_permissions(request, org_a, client, method, url, expected_status):
    graph_a = _graph(org_a)
    body = {"llm_config": LLMConfig.objects.create(custom_name="a-cfg", org=org_a).id} if method == "patch" else {}

    resp = getattr(request.getfixturevalue(client), method)(url.format(graph=graph_a.id), body, format="json")

    assert resp.status_code == expected_status, resp.data
    if expected_status == 201:
        assert FlowAssistantConversation.objects.filter(flow_assistant__graph_id=graph_a.id).exists()


@pytest.mark.parametrize(("owner", "expected_status"), [("own", 200), ("another", 400)])
def test_the_assistants_llm_config_must_be_the_orgs_own(admin_a, org_a, org_b, owner, expected_status):
    llm_config = LLMConfig.objects.create(custom_name="cfg", org=org_a if owner == "own" else org_b)

    resp = admin_a.patch(f"/api/flow-assistants/{_graph(org_a).id}/", {"llm_config": llm_config.id}, format="json")

    assert resp.status_code == expected_status, resp.data
    if expected_status == 400:
        assert "llm_config" in str(resp.data)
