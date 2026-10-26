"""Org scoping of the graph co-editing websocket.

The ws ticket carries only the user, so the graph's organisation decides who may join its
edit channel. A graph owned by another organisation has to look exactly like a missing one
(close 4404), a member of the owning organisation without READ on flows is refused (4403),
and a refused caller must never reach the channel: connected editors see nothing of the
attempt and the caller never enters presence.
"""

import pytest

from rbac.models.enums import Permission, ResourceType
from tables.graph_collab.presence_service import presence_service


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_connect_to_another_orgs_graph_is_rejected_as_missing(
    test_graph, admin_acme, make_communicator
):
    communicator = make_communicator(test_graph.pk, admin_acme)
    connected, code = await communicator.connect()
    assert not connected
    assert code == 4404


@pytest.fixture
def member_without_flows_read(default_org, custom_role_user):
    return custom_role_user(
        default_org, "collab-no-flows@example.com", {ResourceType.AGENTS: Permission.READ}
    )


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_connect_by_member_without_flows_read_is_forbidden(
    test_graph, member_without_flows_read, make_communicator
):
    communicator = make_communicator(test_graph.pk, member_without_flows_read)
    connected, code = await communicator.connect()
    assert not connected
    assert code == 4403


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_connect_by_superadmin_without_membership_is_admitted(
    test_graph, superadmin, make_communicator
):
    communicator = make_communicator(test_graph.pk, superadmin)
    connected, _ = await communicator.connect()
    assert connected

    msg = await communicator.receive_json_from()
    assert msg["type"] == "presence_state"
    assert [editor["user_id"] for editor in msg["editors"]] == [superadmin.pk]

    await communicator.disconnect()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_rejected_foreign_user_is_invisible_to_connected_editors(
    test_graph, test_user, admin_acme, make_communicator
):
    observer = make_communicator(test_graph.pk, test_user)
    observer_connected, _ = await observer.connect()
    assert observer_connected
    await observer.receive_json_from()  # presence_state
    await observer.receive_json_from()  # user_joined (self)

    intruder = make_communicator(test_graph.pk, admin_acme)
    connected, _ = await intruder.connect()

    assert not connected
    assert await observer.receive_nothing()
    assert not presence_service.has_user(test_graph.pk, admin_acme.pk)

    await observer.disconnect()
