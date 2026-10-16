"""Org scoping for the Flow Assistant endpoints (/api/flow-assistants/<graph_id>/...).

These were once IsAuthenticated-only with an unscoped graph lookup, so any user could
read or patch another org's assistant, attach a cross-org LLMConfig, and start a
conversation row against another org's graph. Now: org context + FLOWS verb gate +
row scope (another org's graph is a 404, before any conversation lookup) + an
org-scoped llm_config.

The reply stream authenticates with an SSE ticket that names only the user, so it is
gated by the org that owns the conversation's flow, before the stream (and its LLM
call) starts.
"""

from unittest.mock import MagicMock, patch

import pytest
from django.db.models import Max
from django.test import AsyncClient, Client
from django.urls import reverse
from rest_framework.test import APIClient

from rbac.identity.tickets import sse_ticket_service
from tables.models import Graph
from tables.models.flow_assistant_models import (
    FlowAssistant,
    FlowAssistantConversation,
    FlowAssistantMessage,
)
from tables.models.llm_models import LLMConfig, LLMModel, Provider
from tables.services.llm_clients.base import DoneEvent, TokenEvent
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


# ── GET /api/flow-assistants/<graph_id>/conversations/<id>/stream/ (SSE) ─────


def _member(user, org, role):
    OrganizationUser.objects.create(user=user, org=org, role=role)
    return user


@pytest.fixture
def member_role(db):
    return Role.objects.get(name=BuiltInRole.MEMBER, is_built_in=True, org__isnull=True)


@pytest.fixture
def two_org_user(db, django_user_model, org_a, org_b, member_role):
    """Member of Org A; in Org B their custom role holds no FLOWS permission."""
    user = django_user_model.objects.create_user(email="two-orgs-stream@example.com", password="StrongPass123!")
    _member(user, org_a, member_role)
    return _member(user, org_b, Role.objects.create(name="No flows", org=org_b, is_built_in=False))


@pytest.fixture
def other_member_a(db, django_user_model, org_a, member_role):
    user = django_user_model.objects.create_user(email="other-member-a@example.com", password="StrongPass123!")
    return _member(user, org_a, member_role)


@pytest.fixture
def superadmin_user(db, django_user_model):
    user = django_user_model.objects.create_user(email="superadmin-stream@example.com", password="StrongPass123!")
    user.is_superadmin = True
    user.save()
    return user


def _pending_conversation(user, org) -> FlowAssistantConversation:
    """A conversation of `user` in `org` whose last message waits for the assistant's reply."""
    model = LLMModel.objects.create(name=f"stream-model-{org.id}", llm_provider=Provider.objects.create(name=f"p-{org.id}"))
    assistant = FlowAssistant.objects.create(
        graph=_graph(org), llm_config=LLMConfig.objects.create(custom_name=f"stream-cfg-{org.id}", model=model, org=org)
    )
    conversation = FlowAssistantConversation.objects.create(
        flow_assistant=assistant, organization_user=OrganizationUser.objects.get(user=user, org=org)
    )
    FlowAssistantMessage.objects.create(conversation=conversation, message_index=0, role="user", content="what does this flow do?")
    return conversation


def _stream_url(conversation_id, graph_id):
    return reverse("flow-assistant-stream", args=[graph_id, conversation_id])


def _stream(user, conversation):
    ticket, _ = sse_ticket_service.issue(user)
    return Client().get(_stream_url(conversation.pk, conversation.flow_assistant.graph_id), {"ticket": ticket})


def _missing_conversation(conversation):
    missing_id = FlowAssistantConversation.objects.aggregate(max_id=Max("id"))["max_id"] + 1000
    return FlowAssistantConversation(pk=missing_id, flow_assistant=conversation.flow_assistant)


@pytest.fixture
def llm_client():
    """The LLM client the stream would bill; streams one short plain-text reply."""

    async def reply(messages, tools):
        yield TokenEvent(content="hi")
        yield DoneEvent()

    client = MagicMock()
    client.stream_completion = reply
    with patch("tables.services.flow_assistant.service.get_llm_client", return_value=client) as get_llm_client:
        yield get_llm_client


def test_stream_in_an_org_without_flows_read_is_refused_before_the_llm_is_called(two_org_user, org_b, llm_client):
    response = _stream(two_org_user, _pending_conversation(two_org_user, org_b))

    assert response.status_code == 403, response.content
    assert not response.streaming
    assert response.json()["status_code"] == 403
    llm_client.assert_not_called()


@pytest.mark.parametrize("caller", ["other_member_a", "superadmin_user"])
def test_another_users_conversation_answers_like_a_missing_one(request, two_org_user, org_a, caller, llm_client):
    conversation = _pending_conversation(two_org_user, org_a)
    stranger = request.getfixturevalue(caller)

    foreign = _stream(stranger, conversation)
    missing = _stream(stranger, _missing_conversation(conversation))

    assert foreign.status_code == 404, foreign.content
    assert (foreign.status_code, foreign.content) == (missing.status_code, missing.content)
    llm_client.assert_not_called()


def test_soft_deleted_conversation_is_not_streamed(two_org_user, org_a, llm_client):
    conversation = _pending_conversation(two_org_user, org_a)
    conversation.deleted_at = conversation.started_at
    conversation.save(update_fields=["deleted_at"])

    response = _stream(two_org_user, conversation)

    assert response.status_code == 404, response.content
    llm_client.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_stream_in_an_org_with_flows_read_streams_the_reply(two_org_user, org_a, llm_client):
    from asgiref.sync import sync_to_async

    conversation = await sync_to_async(_pending_conversation)(two_org_user, org_a)
    ticket, _ = await sync_to_async(sse_ticket_service.issue)(two_org_user)

    response = await AsyncClient().get(_stream_url(conversation.pk, conversation.flow_assistant.graph_id), {"ticket": ticket})
    frames = [frame async for frame in response.streaming_content]

    assert response.status_code == 200
    assert response["Content-Type"] == "text/event-stream"
    assert b"event: done\n" in frames
