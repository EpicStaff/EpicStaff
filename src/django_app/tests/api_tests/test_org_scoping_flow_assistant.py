"""Org scoping for the Flow Assistant config endpoint
(GET/PATCH /api/flow-assistants/<graph_id>/).

Before the fix this APIView was IsAuthenticated-only with an unscoped graph
lookup and a plain llm_config field, so any authenticated user could read/patch
another org's assistant and attach a cross-org LLMConfig. Covers the RBAC guide
layers: org context + verb gate (FLOWS) + row scope (cross-org graph → 404) +
org-scoped llm_config FK.
"""

import pytest
from rest_framework.test import APIClient

from tables.models import Graph
from tables.models.flow_assistant_models import FlowAssistantConversation
from tables.models.llm_models import LLMConfig
from tables.models.rbac_models import Organization, OrganizationUser, Role
from tables.models.rbac_models.rbac_enums import BuiltInRole


def _url(graph_id: int) -> str:
    return f"/api/flow-assistants/{graph_id}/"


@pytest.fixture
def org_a(db):
    return Organization.objects.create(name="Org A")


@pytest.fixture
def org_b(db):
    return Organization.objects.create(name="Org B")


def _client(django_user_model, org, email, role_name=BuiltInRole.ORG_ADMIN):
    role = Role.objects.get(name=role_name, is_built_in=True, org__isnull=True)
    user = django_user_model.objects.create_user(email=email, password="StrongPass123!")
    OrganizationUser.objects.create(user=user, org=org, role=role)
    c = APIClient()
    c.force_authenticate(user=user)
    c.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
    return c


@pytest.fixture
def client_a(db, django_user_model, org_a):
    return _client(django_user_model, org_a, "admin_a@example.com")


def _graph(org, name="g"):
    return Graph.objects.create(name=name, metadata={"nodes": [], "edges": []}, org=org)


# ---- row scope: cross-org graph is indistinguishable from missing (404) ----


@pytest.mark.django_db
def test_flow_assistant_config_get_cross_org_graph_404(client_a, org_a, org_b):
    graph_b = _graph(org_b, "b")
    resp = client_a.get(_url(graph_b.id))
    assert resp.status_code == 404, resp.data


@pytest.mark.django_db
def test_flow_assistant_config_patch_cross_org_graph_404(client_a, org_a, org_b):
    graph_b = _graph(org_b, "b")
    resp = client_a.patch(_url(graph_b.id), {}, format="json")
    assert resp.status_code == 404, resp.data


# ---- own graph works ----


@pytest.mark.django_db
def test_flow_assistant_config_get_own_ok(client_a, org_a):
    graph_a = _graph(org_a, "a")
    resp = client_a.get(_url(graph_a.id))
    assert resp.status_code == 200, resp.data


# ---- org-scoped llm_config FK ----


@pytest.mark.django_db
def test_flow_assistant_config_llm_config_cross_org_rejected(client_a, org_a, org_b):
    graph_a = _graph(org_a, "a")
    other = LLMConfig.objects.create(custom_name="b-cfg", org=org_b)
    resp = client_a.patch(_url(graph_a.id), {"llm_config": other.id}, format="json")
    assert resp.status_code == 400, resp.data
    assert "llm_config" in str(resp.data)


@pytest.mark.django_db
def test_flow_assistant_config_llm_config_same_org_ok(client_a, org_a):
    graph_a = _graph(org_a, "a")
    mine = LLMConfig.objects.create(custom_name="a-cfg", org=org_a)
    resp = client_a.patch(_url(graph_a.id), {"llm_config": mine.id}, format="json")
    assert resp.status_code == 200, resp.data


# ---- verb gate: a Viewer (no FLOWS UPDATE) cannot PATCH ----


@pytest.mark.django_db
def test_flow_assistant_config_patch_denied_for_viewer(db, django_user_model, org_a):
    graph_a = _graph(org_a, "a")
    viewer = _client(
        django_user_model, org_a, "viewer_a@example.com", role_name=BuiltInRole.VIEWER
    )
    mine = LLMConfig.objects.create(custom_name="a-cfg", org=org_a)
    resp = viewer.patch(_url(graph_a.id), {"llm_config": mine.id}, format="json")
    assert resp.status_code == 403, resp.data


@pytest.mark.django_db
def test_flow_assistant_config_get_allowed_for_viewer(db, django_user_model, org_a):
    # Viewer has FLOWS READ, so GET is allowed.
    graph_a = _graph(org_a, "a")
    viewer = _client(
        django_user_model, org_a, "viewer_a@example.com", role_name=BuiltInRole.VIEWER
    )
    resp = viewer.get(_url(graph_a.id))
    assert resp.status_code == 200, resp.data


# ── Conversation endpoints ────────────────────────────────────────────────────
#
# Before the fix these used an unscoped graph lookup (`_get_graph_or_404`) and no
# `assert_org_permission`, so any authenticated member could list/start/read a
# conversation against another org's graph — start_conversation in particular
# wrote a cross-org conversation row. Now every endpoint gates on FLOWS READ and
# resolves the graph inside the active org (cross-org graph → 404).


def _conversations_url(graph_id: int) -> str:
    return f"/api/flow-assistants/{graph_id}/conversations/"


def _conversation_url(graph_id: int, conversation_id: int) -> str:
    return f"/api/flow-assistants/{graph_id}/conversations/{conversation_id}/"


def _messages_url(graph_id: int, conversation_id: int) -> str:
    return f"/api/flow-assistants/{graph_id}/conversations/{conversation_id}/messages/"


# ---- row scope: cross-org graph is indistinguishable from missing (404) ----


@pytest.mark.django_db
def test_conversations_list_cross_org_graph_404(client_a, org_a, org_b):
    graph_b = _graph(org_b, "b")
    resp = client_a.get(_conversations_url(graph_b.id))
    assert resp.status_code == 404, resp.data


@pytest.mark.django_db
def test_conversations_start_cross_org_graph_404(client_a, org_a, org_b):
    # The core regression: starting a conversation against another org's graph
    # must 404 before any conversation row is written.
    graph_b = _graph(org_b, "b")
    resp = client_a.post(_conversations_url(graph_b.id), {}, format="json")
    assert resp.status_code == 404, resp.data
    assert not FlowAssistantConversation.objects.filter(
        flow_assistant__graph_id=graph_b.id
    ).exists()


@pytest.mark.django_db
def test_conversation_get_cross_org_graph_404(client_a, org_a, org_b):
    # The graph-scope check runs before the conversation lookup, so a bogus
    # conversation id still surfaces the cross-org graph as 404.
    graph_b = _graph(org_b, "b")
    resp = client_a.get(_conversation_url(graph_b.id, 999999))
    assert resp.status_code == 404, resp.data


@pytest.mark.django_db
def test_conversation_delete_cross_org_graph_404(client_a, org_a, org_b):
    graph_b = _graph(org_b, "b")
    resp = client_a.delete(_conversation_url(graph_b.id, 999999))
    assert resp.status_code == 404, resp.data


@pytest.mark.django_db
def test_send_message_cross_org_graph_404(client_a, org_a, org_b):
    graph_b = _graph(org_b, "b")
    resp = client_a.post(
        _messages_url(graph_b.id, 999999), {"message": "hi"}, format="json"
    )
    assert resp.status_code == 404, resp.data


# ---- own graph works; verb gate allows a Viewer (READ) to use the assistant ----


@pytest.mark.django_db
def test_conversations_list_own_ok(client_a, org_a):
    graph_a = _graph(org_a, "a")
    resp = client_a.get(_conversations_url(graph_a.id))
    assert resp.status_code == 200, resp.data


@pytest.mark.django_db
def test_conversations_start_allowed_for_viewer(db, django_user_model, org_a):
    # Conversation endpoints gate on FLOWS READ, which a Viewer has, so starting
    # a conversation (a "use the assistant" action) is allowed.
    graph_a = _graph(org_a, "a")
    viewer = _client(
        django_user_model, org_a, "viewer_a@example.com", role_name=BuiltInRole.VIEWER
    )
    resp = viewer.post(_conversations_url(graph_a.id), {}, format="json")
    assert resp.status_code == 201, resp.data
    assert FlowAssistantConversation.objects.filter(
        flow_assistant__graph_id=graph_a.id
    ).exists()
