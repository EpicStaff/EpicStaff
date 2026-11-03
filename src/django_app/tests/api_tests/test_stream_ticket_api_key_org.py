"""A stream ticket issued with a USER API key streams only rows of the key's org.

The key acts only in its own org, and EventSource cannot send X-Organization-Id, so the
ticket carries the key's org and each stream refuses another org's row exactly like a
missing one, even for an owner who is a member of that org (or a superadmin). A ticket
issued with a session carries no org and keeps the plain membership rule.
"""

import pytest
from django.db.models import Max
from django.test import Client
from django.urls import reverse
from rest_framework.test import APIClient

from rbac.identity.tickets import sse_ticket_service, ws_ticket_service
from rbac.models import OrganizationUser
from tables.models import Graph, Session
from tables.models.flow_assistant_models import FlowAssistant, FlowAssistantConversation
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403


@pytest.fixture
def member_of_both(member_only, beta, role_member):
    """Member of Acme (from `member_only`) and of Beta."""
    OrganizationUser.objects.create(user=member_only, org=beta, role=role_member)
    return member_only


@pytest.fixture(params=["member_of_both", "superadmin"])
def owner(request):
    """The key owner: may read flows in both orgs, through membership or superadmin."""
    return request.getfixturevalue(request.param)


# ── Ticket issue: POST /api/auth/sse-ticket/ and /api/auth/ws-ticket/ ────────


TICKET_ENDPOINTS = [
    ("sse_ticket", sse_ticket_service),
    ("ws_ticket", ws_ticket_service),
]


@pytest.mark.django_db
@pytest.mark.parametrize(("url_name", "service"), TICKET_ENDPOINTS, ids=["sse", "ws"])
def test_ticket_issued_with_a_user_key_carries_the_key_org(
    issue_api_key, member_of_both, acme, beta, url_name, service
):
    raw_key, _ = issue_api_key(user=member_of_both, org=acme)
    client = APIClient()
    client.credentials(HTTP_X_API_KEY=raw_key, HTTP_X_ORGANIZATION_ID=str(beta.id))

    response = client.post(reverse(url_name))

    assert response.status_code == 200, response.content
    holder = service.consume(response.json()["ticket"])
    assert (holder.user.pk, holder.api_key_org_id) == (member_of_both.pk, acme.id)


@pytest.mark.django_db
@pytest.mark.parametrize(("url_name", "service"), TICKET_ENDPOINTS, ids=["sse", "ws"])
def test_ticket_issued_with_a_session_carries_no_org(
    client_as, member_of_both, url_name, service
):
    response = client_as(member_of_both).post(reverse(url_name))

    assert response.status_code == 200, response.content
    holder = service.consume(response.json()["ticket"])
    assert (holder.user.pk, holder.api_key_org_id) == (member_of_both.pk, None)


# ── GET /api/run-session/subscribe/<id>/ ─────────────────────────────────────


def _session(org) -> Session:
    graph = Graph.objects.create(name=f"ticket-org-flow-{org.pk}", org=org)
    return Session.objects.create(graph=graph, status=Session.SessionStatus.RUN)


def _subscribe(user, session_id: int, api_key_org_id: int | None):
    ticket, _ = sse_ticket_service.issue(user, api_key_org_id=api_key_org_id)
    return Client().get(reverse("run-session-subscribe", args=[session_id]), {"ticket": ticket})


@pytest.mark.django_db
def test_session_stream_with_key_ticket_refuses_another_orgs_session_as_missing(
    owner, acme, beta
):
    missing_id = (Session.objects.aggregate(max_id=Max("id"))["max_id"] or 0) + 1000
    foreign = _subscribe(owner, _session(beta).id, api_key_org_id=acme.id)
    missing = _subscribe(owner, missing_id, api_key_org_id=acme.id)

    assert foreign.status_code == 404, foreign.content
    assert (foreign.status_code, foreign.content) == (missing.status_code, missing.content)


@pytest.mark.django_db
def test_session_stream_with_key_ticket_opens_a_session_of_the_key_org(owner, acme):
    response = _subscribe(owner, _session(acme).id, api_key_org_id=acme.id)

    assert response.status_code == 200, response.content
    assert response.streaming


@pytest.mark.django_db
def test_session_stream_with_session_ticket_opens_any_member_org(owner, beta):
    response = _subscribe(owner, _session(beta).id, api_key_org_id=None)

    assert response.status_code == 200, response.content


# ── GET /api/flow-assistants/<graph_id>/conversations/<id>/stream/ ───────────


def _conversation(user, org) -> FlowAssistantConversation:
    graph = Graph.objects.create(name=f"assistant-flow-{org.pk}", org=org)
    return FlowAssistantConversation.objects.create(
        flow_assistant=FlowAssistant.objects.create(graph=graph),
        organization_user=OrganizationUser.objects.get(user=user, org=org),
    )


def _stream(user, graph_id: int, conversation_id: int, api_key_org_id: int | None):
    ticket, _ = sse_ticket_service.issue(user, api_key_org_id=api_key_org_id)
    url = reverse("flow-assistant-stream", args=[graph_id, conversation_id])
    return Client().get(url, {"ticket": ticket})


@pytest.mark.django_db
def test_assistant_stream_with_key_ticket_refuses_another_orgs_conversation_as_missing(
    member_of_both, acme, beta
):
    conversation = _conversation(member_of_both, beta)
    graph_id = conversation.flow_assistant.graph_id
    missing_id = FlowAssistantConversation.objects.aggregate(max_id=Max("id"))["max_id"] + 1000

    foreign = _stream(member_of_both, graph_id, conversation.pk, api_key_org_id=acme.id)
    missing = _stream(member_of_both, graph_id, missing_id, api_key_org_id=acme.id)

    assert foreign.status_code == 404, foreign.content
    assert (foreign.status_code, foreign.content) == (missing.status_code, missing.content)


@pytest.mark.django_db
@pytest.mark.parametrize(("conversation_org", "key_org"), [("acme", "acme"), ("beta", None)])
def test_assistant_stream_opens_a_conversation_of_the_key_org_or_any_org_for_a_session(
    request, member_of_both, conversation_org, key_org
):
    conversation = _conversation(member_of_both, request.getfixturevalue(conversation_org))
    api_key_org_id = None if key_org is None else request.getfixturevalue(key_org).id

    response = _stream(
        member_of_both,
        conversation.flow_assistant.graph_id,
        conversation.pk,
        api_key_org_id=api_key_org_id,
    )

    assert response.status_code == 200, response.content
    assert response.streaming
