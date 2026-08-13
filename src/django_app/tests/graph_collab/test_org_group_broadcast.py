"""The graph-edit WS socket joins the org-wide ``org_{org_id}``
group (in addition to the per-graph ``graph_edit_{graph_id}`` group) on
connect, and leaves it on disconnect.

This is what lets org-scoped storage-tree broadcasts (upload/mkdir/delete/
move/rename/copy — including on files attached to no graph at all) reach
every open "Add files" dialog for the graph's org, not just per-graph
attach/detach events.
"""

import pytest
from channels.layers import get_channel_layer

from tables.models import Graph, Organization
from tables.models.rbac_models import OrganizationUser

from tests.graph_collab.conftest import _drain_connect


@pytest.fixture
def org(db):
    return Organization.objects.create(name="org-group-broadcast-test-org")


@pytest.fixture
def other_org(db):
    return Organization.objects.create(name="org-group-broadcast-other-org")


@pytest.fixture
def org_graph(db, org):
    return Graph.objects.create(name="org-group-broadcast-test-graph", org=org)


@pytest.fixture(autouse=True)
def test_user_membership_in_org(db, org, test_user, org_admin_role):
    """`test_user` (from graph_collab/conftest.py) is only ever seeded as a
    member of `default_org`, not this file's own `org` fixture. The
    consumer's connect() gate requires org membership + FLOWS.UPDATE, so
    give `test_user` Org Admin rights in `org` here to keep these
    connect-and-relay tests passing under that gate."""
    OrganizationUser.objects.create(user=test_user, org=org, role=org_admin_role)


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_connect_joins_org_group_and_relays_org_broadcast(
    org, org_graph, test_user, make_communicator
):
    communicator = make_communicator(org_graph.pk, test_user)
    connected, _ = await communicator.connect()
    assert connected
    await _drain_connect(communicator)

    channel_layer = get_channel_layer()
    await channel_layer.group_send(
        f"org_{org.id}",
        {"type": "graph_files_changed", "graph_id": None, "editor": None},
    )

    message = await communicator.receive_json_from()
    assert message["type"] == "graph_files_changed"
    assert message["graph_id"] is None

    await communicator.disconnect()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_connect_does_not_receive_other_orgs_broadcast(
    org, other_org, org_graph, test_user, make_communicator
):
    communicator = make_communicator(org_graph.pk, test_user)
    connected, _ = await communicator.connect()
    assert connected
    await _drain_connect(communicator)

    channel_layer = get_channel_layer()
    await channel_layer.group_send(
        f"org_{other_org.id}",
        {"type": "graph_files_changed", "graph_id": None, "editor": None},
    )

    assert await communicator.receive_nothing(timeout=0.3)

    await communicator.disconnect()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_disconnect_discards_org_group_membership(
    org, org_graph, test_user, make_communicator
):
    communicator = make_communicator(org_graph.pk, test_user)
    connected, _ = await communicator.connect()
    assert connected
    await _drain_connect(communicator)
    await communicator.disconnect()

    channel_layer = get_channel_layer()
    org_group_channels = channel_layer.groups.get(f"org_{org.id}", {})
    assert org_group_channels == {}
