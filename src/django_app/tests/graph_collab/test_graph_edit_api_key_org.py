"""The graph co-editing websocket opened with a USER API key's ticket joins only graphs of
the key's org; another org's graph closes like a missing one (4404), even for an owner who
is a member of that org or a superadmin. A session ticket keeps the plain membership rule.
"""

import pytest
from asgiref.sync import sync_to_async
from channels.testing import WebsocketCommunicator

from rbac.models import OrganizationUser
from rbac.identity.tickets import ws_ticket_service
from tables.graph_collab.ws_auth import TicketAuthMiddleware
from tables.models import Graph
from tests.graph_collab.conftest import application


@pytest.fixture
def member_of_both(member_only, beta, role_member):
    """Member of Acme (from `member_only`) and of Beta."""
    OrganizationUser.objects.create(user=member_only, org=beta, role=role_member)
    return member_only


@pytest.fixture(params=["member_of_both", "superadmin"])
def owner(request):
    """The key owner: may read flows in both orgs, through membership or superadmin."""
    return request.getfixturevalue(request.param)


async def _connect(user, org, api_key_org_id):
    graph = await sync_to_async(Graph.objects.create)(name=f"ws-ticket-org-{org.pk}", org=org)
    ticket, _ = await sync_to_async(ws_ticket_service.issue)(user, api_key_org_id=api_key_org_id)
    communicator = WebsocketCommunicator(
        TicketAuthMiddleware(application), f"ws/graphs/{graph.pk}/edit/?ticket={ticket}"
    )
    connected, code = await communicator.connect()
    if connected:
        await communicator.disconnect()
    return connected, code


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_key_ticket_refuses_another_orgs_graph_as_missing(fake_redis, owner, acme, beta):
    assert await _connect(owner, beta, api_key_org_id=acme.id) == (False, 4404)


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_key_ticket_joins_a_graph_of_the_key_org(fake_redis, owner, acme):
    connected, _ = await _connect(owner, acme, api_key_org_id=acme.id)

    assert connected


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_session_ticket_joins_a_graph_of_any_member_org(fake_redis, owner, beta):
    connected, _ = await _connect(owner, beta, api_key_org_id=None)

    assert connected
