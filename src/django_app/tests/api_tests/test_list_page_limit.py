"""`?limit=` on list routes is capped at 1000: a larger value returns one full page and a `next` link.

Without the cap a member could ask for a whole table in one request and tie up a worker.
"""

import uuid

import pytest
from django.utils import timezone

from rbac.models import OrganizationUser
from tables.models import FlowAssistant, FlowAssistantConversation, Graph
from tables.models.graph_models import GraphSessionMessage
from tables.models.session_models import Session
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

pytestmark = pytest.mark.django_db

ROW_COUNT = 1001
SESSION_MESSAGES_URL = "/api/graph-session-messages/"


@pytest.fixture
def acme_member_client(client_as, member_only, acme):
    client = client_as(member_only)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
    return client


@pytest.fixture
def session_with_messages(acme):
    graph = Graph.objects.create(name="Paged messages", org=acme)
    session = Session.objects.create(graph=graph, status=Session.SessionStatus.END, variables={})
    GraphSessionMessage.objects.bulk_create(
        GraphSessionMessage(
            session=session,
            created_at=timezone.now(),
            message_data={"message_type": "start"},
            uuid=uuid.uuid4(),
        )
        for _ in range(ROW_COUNT)
    )
    return session


@pytest.fixture
def graph_with_conversations(acme, member_only):
    graph = Graph.objects.create(name="Paged conversations", org=acme)
    assistant = FlowAssistant.objects.create(graph=graph)
    organization_user = OrganizationUser.objects.get(user=member_only, org=acme)
    FlowAssistantConversation.objects.bulk_create(
        FlowAssistantConversation(flow_assistant=assistant, organization_user=organization_user)
        for _ in range(ROW_COUNT)
    )
    return graph


@pytest.mark.parametrize(
    ("limit", "expected_page_length"),
    [(None, 50), (1000, 1000), (1001, 1000), (10_000_000, 1000)],
)
def test_session_messages_page_is_capped(acme_member_client, session_with_messages, limit, expected_page_length):
    params = {"session_id": session_with_messages.id}
    if limit is not None:
        params["limit"] = limit

    response = acme_member_client.get(SESSION_MESSAGES_URL, params)

    assert response.status_code == 200, response.content
    page = response.json()
    assert page["count"] == ROW_COUNT
    assert len(page["results"]) == expected_page_length
    assert page["next"] is not None


def test_session_messages_next_link_returns_the_rest(acme_member_client, session_with_messages):
    first = acme_member_client.get(SESSION_MESSAGES_URL, {"session_id": session_with_messages.id, "limit": 5000})
    assert first.status_code == 200, first.content
    rest = acme_member_client.get(first.json()["next"])

    assert rest.status_code == 200, rest.content
    assert len(rest.json()["results"]) == ROW_COUNT - 1000
    assert rest.json()["next"] is None


def test_flow_assistant_conversations_page_is_capped(acme_member_client, graph_with_conversations):
    response = acme_member_client.get(
        f"/api/flow-assistants/{graph_with_conversations.id}/conversations/", {"limit": 5000}
    )

    assert response.status_code == 200, response.content
    page = response.json()
    assert page["count"] == ROW_COUNT
    assert len(page["results"]) == 1000
    assert page["next"] is not None


def test_flow_assistant_audit_page_is_capped(superadmin_in_acme, graph_with_conversations):
    response = superadmin_in_acme.get("/api/flow-assistants/audit/conversations/", {"limit": 5000})

    assert response.status_code == 200, response.content
    page = response.json()
    assert page["count"] == ROW_COUNT
    assert len(page["results"]) == 1000
    assert page["next"] is not None
