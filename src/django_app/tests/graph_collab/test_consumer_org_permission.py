"""
Tests for `GraphEditConsumer.connect()` org-membership + flows-access gating,
and for live-session revocation keeping an already-open socket in sync with
the connected user's current access (role downgrade, membership removal,
superadmin revocation, org deactivation).

These tests cover:

connect()-time gating:
1. A same-org member with edit rights (Org Admin) is accepted.
2. A user with no membership in the graph's org is rejected with 4403 +
   the org-membership-required reason.
3. A same-org Viewer (has flows READ, lacks UPDATE) connects successfully,
   in a read-only capacity.
4. A superadmin with no membership in the graph's org is still accepted
   (platform bypass preserved).
5. Unauthenticated connect is rejected with 4401 + reason.
6. A bad (non-integer) graph_id is rejected with 4400 + reason.
6b. A well-formed but nonexistent graph id is rejected with 4404 + reason
    (distinct code path from 6: `int()` succeeds, the DB lookup fails).

Live-session access changes:
7. `change_role` downgrading a connected Member to Viewer (loses UPDATE,
   keeps READ) does NOT disconnect them — it downgrades them to read-only,
   verified by a subsequent write attempt being rejected.
8. `remove_member` on a connected user closes their socket with 4403
   (genuine zero access).
9. `revoke_superadmin` on a user with live connections in two different
   orgs, both of which grant only the Viewer role, downgrades both
   connections to read-only rather than disconnecting them.
10. A `permission_changed` broadcast for a DIFFERENT user_id on the same
    org group leaves the connection open (no false positive).
11. A role change that still satisfies UPDATE (Org Admin -> Member) leaves
    the connection open (no false disconnect).

Per-message write authorization (new — this consumer had zero per-message
auth prior to this change):
12. A connected Viewer's state-mutating op is rejected with
    `op_rejected`/`permission_denied`, and the live snapshot is unchanged.
13. A connected Viewer's `node_locked` is rejected with an `ErrorMessage`,
    and no lock is granted.
14. A connected Viewer's `cursor_moved` still relays normally (no gate).
15. A Member downgraded to Viewer mid-session has their very first write
    after the downgrade rejected — proves the cached bitmask is actually
    refreshed and used, not just checked once at connect time.

Org-wide group membership on connect (in addition to the per-graph
`graph_edit_{graph_id}` group): the socket also joins `org_{org_id}` on
connect and leaves it on disconnect, which is what lets org-scoped
storage-tree broadcasts (upload/mkdir/delete/move/rename/copy — including
on files attached to no graph at all) reach every open "Add files" dialog
for the graph's org, not just per-graph attach/detach events.
16. Connecting joins the org group, and a `graph_files_changed` broadcast
    sent to that org's group is relayed to the connection.
17. A broadcast sent to a DIFFERENT org's group does not reach the connection.
18. Disconnecting discards the connection's org group membership.

User-wide access changes reach the socket through the per-user
`graph_edit_user_{user_id}` group, so they work even when the user holds no membership:
19. A revoked superadmin with NO memberships is closed with 4403.
20. `set_user_active(False)` closes the socket with 4403.
21. `delete_user` closes the socket with 4403.
22. A custom-role `update_role` that drops flows UPDATE sends
    `edit_rights_changed{can_edit: false}` and keeps the socket open.
23. Connecting joins the user group; disconnecting discards it.

More live-session access changes:
24. `change_role` upgrading a connected Viewer to Member sends
    `edit_rights_changed{can_edit: true}`, and the next write is applied.
25. One user with sessions in two orgs: deactivating org A, or removing the
    user's membership in A, closes the A session with 4403 and does not
    re-check the B session at all.
26. `delete_user` closes that user's sessions in both orgs with 4403.
"""

import asyncio

import pytest

from asgiref.sync import sync_to_async
from channels.layers import get_channel_layer
from django.contrib.auth import get_user_model

from tables.graph_collab import graph_state_service as _gss_module
from tables.graph_collab import lock_service as _ls_module
from tables.graph_collab.constants import CURSOR_FLUSH_INTERVAL_SECONDS
from rbac.models import Organization, OrganizationUser, Role, RolePermission
from tables.models import Graph
from rbac.governance.memberships import MembershipManagementService
from rbac.governance.organizations import OrganizationManagementService
from rbac.governance.roles import RoleManagementService
from rbac.governance.users import UserManagementService
from tables.graph_collab.groups import org_group_name, user_group_name
from rbac.models.enums import Permission, ResourceType

from tests.graph_collab.conftest import (
    _make_communicator,
    _drain_connect,
    apply_create_op,
    editor_payload,
    connect_pair,
)


async def _connect_raw(communicator, timeout: float = 1.0) -> dict:
    """Trigger a WS connect and return the raw ASGI response message
    (unlike ``communicator.connect()``, this preserves the ``reason`` key
    on a ``websocket.close`` response)."""
    await communicator.send_input({"type": "websocket.connect"})
    return await communicator.receive_output(timeout)


@sync_to_async
def _membership_id(user, org) -> int:
    return OrganizationUser.objects.get(user=user, org=org).id


async def _receive_close(communicator, timeout: float = 1.0) -> dict:
    """Wait for the server to close the socket and return the raw
    ``websocket.close`` ASGI message (code + optional reason)."""
    return await communicator.receive_output(timeout)


async def _connect_session(graph_id: int, user):
    """Open a live editor session and drain its connect-time messages."""
    communicator = _make_communicator(graph_id, user)
    connected, _ = await communicator.connect()
    assert connected
    await _drain_connect(communicator)
    return communicator


@pytest.fixture
def other_org(db):
    return Organization.objects.create(name="Other Organization")


@pytest.fixture
def org(db):
    return Organization.objects.create(name="org-group-broadcast-test-org")


@pytest.fixture
def isolated_org_graph(db, org):
    """Deliberately shadows conftest's `org_graph` (which lives in
    `default_org`): these tests assert cross-org isolation, so the graph
    must belong to a non-default org."""
    return Graph.objects.create(name="org-group-broadcast-test-graph", org=org)


@pytest.fixture
def grant_test_user_membership_in_org(db, org, test_user, org_admin_role):
    """`test_user` is seeded in `default_org` only, so it needs membership in
    this file's own non-default `org` to pass connect()'s gate. Deliberately
    not autouse — only the org-group-broadcast tests need it."""
    OrganizationUser.objects.create(user=test_user, org=org, role=org_admin_role)


@pytest.fixture
def viewer_role(db):
    return Role.objects.get(name="Viewer", is_built_in=True, org__isnull=True)


@pytest.fixture
def member_role(db):
    return Role.objects.get(name="Member", is_built_in=True, org__isnull=True)


@pytest.fixture
def other_org_member(db, other_org, org_admin_role):
    """A user who is only a member of `other_org` — not the graph's org."""
    user = get_user_model().objects.create_user(
        email="other-org-member@example.com",
        password="TestPass123!",
    )
    OrganizationUser.objects.create(user=user, org=other_org, role=org_admin_role)
    return user


@pytest.fixture
def viewer_member(db, default_org, viewer_role):
    """A user who is a member of the graph's org but only holds the Viewer role."""
    user = get_user_model().objects.create_user(
        email="viewer-member@example.com",
        password="TestPass123!",
    )
    OrganizationUser.objects.create(user=user, org=default_org, role=viewer_role)
    return user


@pytest.fixture
def member_member(db, default_org, member_role):
    """A user who is a Member of the graph's org — Member has flows UPDATE,
    so this fixture is used as the "connected, then downgraded" target."""
    user = get_user_model().objects.create_user(
        email="member-member@example.com",
        password="TestPass123!",
    )
    OrganizationUser.objects.create(user=user, org=default_org, role=member_role)
    return user


@pytest.fixture
def fake_cursor_redis_for_permission_tests(monkeypatch):
    """Patch RedisService's async client with a shared in-memory fake so the
    cursor_moved relay test doesn't require a live Redis server. Scoped to
    this file only — other tests here don't touch the cursor pub/sub path."""
    import fakeredis.aioredis

    from tables.services import redis_service as _rs_module

    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(
        type(_rs_module.RedisService()),
        "async_redis_client",
        property(lambda self: fake),
    )
    return fake


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_connect_org_member_with_edit_rights_is_accepted(org_graph, regular_user):
    """regular_user is an Org Admin member of default_org — has flows UPDATE."""
    communicator = _make_communicator(org_graph.pk, regular_user)
    connected, _ = await communicator.connect()
    assert connected
    await _drain_connect(communicator)
    await communicator.disconnect()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_connect_non_org_member_is_rejected(org_graph, other_org_member):
    """Core cross-org attacker case: a user with no membership in the graph's
    org must be rejected, not silently granted read/write access."""
    communicator = _make_communicator(org_graph.pk, other_org_member)
    response = await _connect_raw(communicator)
    assert response["type"] == "websocket.close"
    assert response["code"] == 4403
    assert response["reason"] == "You are not a member of this organization."
    await communicator.disconnect()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_connect_viewer_role_connects_read_only(org_graph, viewer_member):
    """A Viewer is a genuine member of the graph's org and has flows READ, but
    lacks flows UPDATE. Connect() only requires READ, so the socket accepts —
    the Viewer gets a live, read-only view (cursors/edits/presence), with
    writes rejected server-side per message rather than the connection being
    refused outright."""
    communicator = _make_communicator(org_graph.pk, viewer_member)
    connected, _ = await communicator.connect()
    assert connected
    await _drain_connect(communicator)
    await communicator.disconnect()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_connect_unauthenticated_is_rejected(org_graph):
    """No user in scope (AnonymousUser) must be rejected before any DB or
    permission check — 4401 with an authentication-required reason."""
    communicator = _make_communicator(org_graph.pk, user=None)
    response = await _connect_raw(communicator)
    assert response["type"] == "websocket.close"
    assert response["code"] == 4401
    assert response["reason"] == "Authentication required."
    await communicator.disconnect()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_connect_invalid_graph_id_is_rejected(regular_user):
    """A non-integer graph_id must be rejected with 4400 before any DB lookup
    is attempted. The production URL pattern (``routing.py``) already
    constrains ``graph_id`` to ``\\d+``, so this exercises connect()'s own
    ``int()`` guard as defense-in-depth via a permissive router, rather than
    reflecting a route reachable through the real ASGI router."""
    from channels.routing import URLRouter
    from django.urls import re_path

    from tables.graph_collab.consumers import GraphEditConsumer
    from channels.testing import WebsocketCommunicator

    application = URLRouter(
        [re_path(r"ws/graphs/(?P<graph_id>[^/]+)/edit/$", GraphEditConsumer.as_asgi())]
    )
    communicator = WebsocketCommunicator(application, "ws/graphs/not-an-int/edit/")
    communicator.scope["user"] = regular_user
    response = await _connect_raw(communicator)
    assert response["type"] == "websocket.close"
    assert response["code"] == 4400
    assert response["reason"] == "Invalid graph id."
    await communicator.disconnect()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_connect_nonexistent_graph_is_rejected(test_user, make_communicator):
    """A well-formed integer graph_id for a graph that doesn't exist must be
    rejected with 4404 — distinct from the non-integer-id 4400 case above."""
    communicator = make_communicator(999999, test_user)
    response = await _connect_raw(communicator)
    assert response["type"] == "websocket.close"
    assert response["code"] == 4404
    assert response["reason"] == "Graph not found."
    await communicator.disconnect()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_connect_superadmin_bypasses_org_membership(org_graph, superadmin_user):
    """Superadmin has no membership row in default_org at all, but the
    platform-wide bypass in PermissionResolver must still grant access."""
    communicator = _make_communicator(org_graph.pk, superadmin_user)
    connected, _ = await communicator.connect()
    assert connected
    await _drain_connect(communicator)
    await communicator.disconnect()


# ---------------------------------------------------------------------------
# Live-session revocation: change_role / remove_member / revoke_superadmin
# must disconnect an already-open socket, not just block future connects.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_change_role_downgrade_stays_connected_read_only(
    org_graph, default_org, member_member, viewer_role, superadmin_user
):
    """member_member is connected as a Member (has flows UPDATE). Demoting
    them to Viewer (keeps READ, loses UPDATE) must NOT close their
    already-open socket — it downgrades the connection to read-only. Proven
    two ways: no close is observed, and a state-mutating op sent afterward
    is rejected with reason=permission_denied (not silently accepted)."""
    communicator = _make_communicator(org_graph.pk, member_member)
    connected, _ = await communicator.connect()
    assert connected
    await _drain_connect(communicator)

    service = MembershipManagementService()
    await sync_to_async(service.change_role)(
        actor=superadmin_user,
        membership_id=await _membership_id(member_member, default_org),
        role_id=viewer_role.id,
    )

    rights_changed = await communicator.receive_json_from()
    assert rights_changed["type"] == "edit_rights_changed"
    assert rights_changed["can_edit"] is False

    await communicator.send_json_to(
        {
            "type": "node_created",
            "node": {"temp_id": "n1", "node_name": "Node A"},
            "list_key": "python_node_list",
            "editor": {
                "user_id": member_member.pk,
                "display_name": "x",
                "avatar_url": None,
            },
        }
    )
    rejection = await communicator.receive_json_from()
    assert rejection["type"] == "op_rejected"
    assert rejection["reason"] == "permission_denied"

    await communicator.disconnect()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_change_role_preserving_update_does_not_disconnect(
    org_graph, default_org, regular_user, second_user, member_role, superadmin_user
):
    """regular_user is connected as an Org Admin. Changing their role to
    Member — which still grants flows UPDATE — must NOT disconnect them.
    ``second_user`` (also an Org Admin in default_org, not connected) keeps
    the last-Org-Admin guard from rejecting the demotion outright."""
    communicator = _make_communicator(org_graph.pk, regular_user)
    connected, _ = await communicator.connect()
    assert connected
    await _drain_connect(communicator)

    service = MembershipManagementService()
    await sync_to_async(service.change_role)(
        actor=superadmin_user,
        membership_id=await _membership_id(regular_user, default_org),
        role_id=member_role.id,
    )

    assert await communicator.receive_nothing(timeout=0.3)
    await communicator.disconnect()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_change_role_upgrade_grants_edit_rights_to_live_session(
    org_graph, default_org, viewer_member, member_role, superadmin_user
):
    """A connected Viewer upgraded to Member (gains flows UPDATE) is told it
    can edit now, and its next write is applied, not rejected."""
    communicator = await _connect_session(org_graph.pk, viewer_member)

    await sync_to_async(MembershipManagementService().change_role)(
        actor=superadmin_user,
        membership_id=await _membership_id(viewer_member, default_org),
        role_id=member_role.id,
    )

    rights_changed = await communicator.receive_json_from()
    assert rights_changed["type"] == "edit_rights_changed"
    assert rights_changed["can_edit"] is True

    await apply_create_op(communicator, org_graph.pk, viewer_member, "upgraded-viewer-node")
    assert await communicator.receive_nothing(timeout=0.3)

    await communicator.disconnect()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_remove_membership_disconnects_live_session(
    org_graph, default_org, member_member, superadmin_user
):
    """Removing member_member's membership entirely must close their
    already-open socket with 4403."""
    communicator = _make_communicator(org_graph.pk, member_member)
    connected, _ = await communicator.connect()
    assert connected
    await _drain_connect(communicator)

    service = MembershipManagementService()
    await sync_to_async(service.remove_member)(
        actor=superadmin_user,
        membership_id=await _membership_id(member_member, default_org),
    )

    response = await _receive_close(communicator)
    assert response["type"] == "websocket.close"
    assert response["code"] == 4403
    await communicator.disconnect()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_revoke_superadmin_downgrades_sessions_in_multiple_orgs_to_read_only(
    default_org, other_org, viewer_role, superadmin_user
):
    """`is_superadmin` is global, not per-org, so one user can hold live
    sessions in several orgs at once. Revoking it leaves only the Viewer role
    in each org, which downgrades both sockets to read-only rather than
    disconnecting them."""
    target = await sync_to_async(get_user_model().objects.create_superuser)(
        email="second-superadmin@example.com",
        password="TestPass123!",
    )
    await sync_to_async(OrganizationUser.objects.create)(
        user=target, org=default_org, role=viewer_role
    )
    await sync_to_async(OrganizationUser.objects.create)(
        user=target, org=other_org, role=viewer_role
    )

    graph_in_default_org = await sync_to_async(Graph.objects.create)(
        name="revoke-superadmin-default-org-graph", org=default_org
    )
    graph_in_other_org = await sync_to_async(Graph.objects.create)(
        name="revoke-superadmin-other-org-graph", org=other_org
    )

    communicator_a = _make_communicator(graph_in_default_org.pk, target)
    connected_a, _ = await communicator_a.connect()
    assert connected_a
    await _drain_connect(communicator_a)

    communicator_b = _make_communicator(graph_in_other_org.pk, target)
    connected_b, _ = await communicator_b.connect()
    assert connected_b
    await _drain_connect(communicator_b)

    service = UserManagementService()
    await sync_to_async(service.revoke_superadmin)(
        actor=superadmin_user,
        target_user_id=target.id,
    )

    for communicator in (communicator_a, communicator_b):
        rights_changed = await communicator.receive_json_from()
        assert rights_changed["type"] == "edit_rights_changed"
        assert rights_changed["can_edit"] is False

    for communicator in (communicator_a, communicator_b):
        await communicator.send_json_to(
            {
                "type": "node_created",
                "node": {"temp_id": "n1", "node_name": "Node A"},
                "list_key": "python_node_list",
                "editor": editor_payload(target),
            }
        )
        rejection = await communicator.receive_json_from()
        assert rejection["type"] == "op_rejected"
        assert rejection["reason"] == "permission_denied"

    await communicator_a.disconnect()
    await communicator_b.disconnect()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_permission_changed_for_other_user_leaves_socket_untouched(
    org_graph, default_org, member_member, viewer_role, superadmin_user
):
    """A permission_changed broadcast naming a DIFFERENT user_id on the same
    org group must leave the connected socket completely untouched — no
    close frame and no edit_rights_changed message."""
    communicator = _make_communicator(org_graph.pk, member_member)
    connected, _ = await communicator.connect()
    assert connected
    await _drain_connect(communicator)

    other_user = await sync_to_async(get_user_model().objects.create_user)(
        email="unrelated-user@example.com",
        password="TestPass123!",
    )

    from channels.layers import get_channel_layer

    from tables.graph_collab.groups import org_group_name

    channel_layer = get_channel_layer()
    await channel_layer.group_send(
        org_group_name(default_org.id),
        {"type": "permission_changed", "user_id": other_user.id},
    )

    assert await communicator.receive_nothing(timeout=0.3)
    await communicator.disconnect()


# ---------------------------------------------------------------------------
# Live-session revocation: organization deactivation must also disconnect
# every already-open socket belonging to a member of that org. The service
# sends one `org_access_changed` signal per member after commit; the tables
# receiver forwards each one to the org group as `permission_changed`.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_deactivate_organization_disconnects_all_connected_members(
    default_org, other_org, regular_user, member_member
):
    """Deactivating default_org must close every connected member's socket,
    not just one. ``other_org`` merely exists so the last-active-organization
    guard in ``_assert_can_deactivate`` doesn't reject the deactivation.

    Each member connects to a *different* graph within default_org — sharing
    one graph would make the second connect broadcast a ``user_joined``
    presence message to the first communicator, which would be mistaken for
    the close response by ``_receive_close``."""
    graph_a = await sync_to_async(Graph.objects.create)(
        name="deactivate-member-a-graph", org=default_org
    )
    graph_b = await sync_to_async(Graph.objects.create)(
        name="deactivate-member-b-graph", org=default_org
    )

    communicator_a = _make_communicator(graph_a.pk, regular_user)
    connected_a, _ = await communicator_a.connect()
    assert connected_a
    await _drain_connect(communicator_a)

    communicator_b = _make_communicator(graph_b.pk, member_member)
    connected_b, _ = await communicator_b.connect()
    assert connected_b
    await _drain_connect(communicator_b)

    service = OrganizationManagementService()
    await sync_to_async(service.deactivate_organization)(org_id=default_org.id)

    response_a = await _receive_close(communicator_a)
    assert response_a["type"] == "websocket.close"
    assert response_a["code"] == 4403
    assert (
        response_a["reason"]
        == "Your access to this flow has changed. Please reconnect."
    )

    response_b = await _receive_close(communicator_b)
    assert response_b["type"] == "websocket.close"
    assert response_b["code"] == 4403
    assert (
        response_b["reason"]
        == "Your access to this flow has changed. Please reconnect."
    )

    await communicator_a.disconnect()
    await communicator_b.disconnect()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_deactivate_organization_does_not_disconnect_other_org_members(
    default_org, other_org, other_org_member, org_admin_role
):
    """Members of a DIFFERENT, still-active org must be unaffected when some
    other org gets deactivated — no false-positive disconnect for any socket
    in the unrelated org, checked across two separate connections."""
    graph_a = await sync_to_async(Graph.objects.create)(
        name="deactivate-other-org-graph-a", org=other_org
    )
    graph_b = await sync_to_async(Graph.objects.create)(
        name="deactivate-other-org-graph-b", org=other_org
    )

    second_other_org_member = await sync_to_async(get_user_model().objects.create_user)(
        email="second-other-org-member@example.com",
        password="TestPass123!",
    )
    await sync_to_async(OrganizationUser.objects.create)(
        user=second_other_org_member, org=other_org, role=org_admin_role
    )

    communicator_a = _make_communicator(graph_a.pk, other_org_member)
    connected_a, _ = await communicator_a.connect()
    assert connected_a
    await _drain_connect(communicator_a)

    communicator_b = _make_communicator(graph_b.pk, second_other_org_member)
    connected_b, _ = await communicator_b.connect()
    assert connected_b
    await _drain_connect(communicator_b)

    service = OrganizationManagementService()
    await sync_to_async(service.deactivate_organization)(org_id=default_org.id)

    assert await communicator_a.receive_nothing(timeout=0.3)
    assert await communicator_b.receive_nothing(timeout=0.3)

    await communicator_a.disconnect()
    await communicator_b.disconnect()


# ---------------------------------------------------------------------------
# Per-message write authorization: a read-only (Viewer) connection may relay
# safe presence traffic but must have every state-mutating message rejected
# server-side.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_viewer_state_mutating_op_is_rejected_and_snapshot_unchanged(
    org_graph, viewer_member
):
    """A connected Viewer sending a state-mutating op (node_created, one of
    _STATE_OP_TYPES via _handle_relay) must receive op_rejected with
    reason=permission_denied, and the op must never reach apply_op — the
    live snapshot's python_node_list must stay exactly as seeded (empty)."""
    communicator = _make_communicator(org_graph.pk, viewer_member)
    connected, _ = await communicator.connect()
    assert connected
    await _drain_connect(communicator)

    await communicator.send_json_to(
        {
            "type": "node_created",
            "node": {"temp_id": "n1", "node_name": "Node A"},
            "list_key": "python_node_list",
            "editor": editor_payload(viewer_member),
        }
    )

    rejection = await communicator.receive_json_from()
    assert rejection["type"] == "op_rejected"
    assert rejection["op_type"] == "node_created"
    assert rejection["reason"] == "permission_denied"
    assert rejection["list_key"] == "python_node_list"

    snapshot = await _gss_module.graph_state_service.get_snapshot(org_graph.pk)
    assert snapshot is not None
    assert snapshot["python_node_list"] == []

    await communicator.disconnect()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_viewer_connection_created_rejection_reports_node_ref_from_connection(
    org_graph, viewer_member
):
    """A rejected `connection_created` must build `node_ref` from the
    `.connection` dict, not from a `.node` attribute that doesn't exist on
    this message type (regression: previously always {id: None, temp_id: None})."""
    communicator = _make_communicator(org_graph.pk, viewer_member)
    connected, _ = await communicator.connect()
    assert connected
    await _drain_connect(communicator)

    await communicator.send_json_to(
        {
            "type": "connection_created",
            "connection": {"temp_id": "con-1", "start_node_id": 1, "end_node_id": 2},
            "list_key": "edge_list",
            "editor": editor_payload(viewer_member),
        }
    )

    rejection = await communicator.receive_json_from()
    assert rejection["type"] == "op_rejected"
    assert rejection["op_type"] == "connection_created"
    assert rejection["reason"] == "permission_denied"
    assert rejection["node_ref"] == {"id": None, "temp_id": "con-1"}

    await communicator.disconnect()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_viewer_connection_deleted_rejection_reports_node_ref_from_connection_id(
    org_graph, viewer_member
):
    """A rejected single-entity `connection_deleted` must build `node_ref`
    from its `.connection_id`/`.temp_id` sibling attributes (not a nested
    `.connection` dict — this message type has no such attribute). Here the
    connection is already persisted, so `connection_id` is a real int and
    `temp_id` is None."""
    communicator = _make_communicator(org_graph.pk, viewer_member)
    connected, _ = await communicator.connect()
    assert connected
    await _drain_connect(communicator)

    await communicator.send_json_to(
        {
            "type": "connection_deleted",
            "connection_id": 7,
            "list_key": "edge_list",
            "editor": editor_payload(viewer_member),
        }
    )

    rejection = await communicator.receive_json_from()
    assert rejection["type"] == "op_rejected"
    assert rejection["op_type"] == "connection_deleted"
    assert rejection["reason"] == "permission_denied"
    assert rejection["node_ref"] == {"id": 7, "temp_id": None}

    await communicator.disconnect()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_viewer_connections_deleted_rejection_reports_node_ref_from_first_ref(
    org_graph, viewer_member
):
    """A rejected bulk `connections_deleted` must build `node_ref` from the
    first entry of `.refs` (regression: previously always
    {id: None, temp_id: None} since this message type has no `.node`)."""
    communicator = _make_communicator(org_graph.pk, viewer_member)
    connected, _ = await communicator.connect()
    assert connected
    await _drain_connect(communicator)

    await communicator.send_json_to(
        {
            "type": "connections_deleted",
            "refs": [
                {"list_key": "edge_list", "id": 42},
                {"list_key": "edge_list", "id": 43},
            ],
            "editor": editor_payload(viewer_member),
        }
    )

    rejection = await communicator.receive_json_from()
    assert rejection["type"] == "op_rejected"
    assert rejection["op_type"] == "connections_deleted"
    assert rejection["reason"] == "permission_denied"
    assert rejection["node_ref"] == {"id": 42, "temp_id": None}

    await communicator.disconnect()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_viewer_connection_waypoints_updated_with_real_id_rejection_reports_node_ref_from_connection_id(
    org_graph, viewer_member
):
    """A rejected `connection_waypoints_updated` targeting an already-persisted
    connection (int `connection_id`) must build `node_ref` from
    `.connection_id` (confirmed live-trace regression: this exact op type
    always came back with node_ref: {id: None, temp_id: None} before the fix,
    since it has neither `.node` nor `.connection`)."""
    communicator = _make_communicator(org_graph.pk, viewer_member)
    connected, _ = await communicator.connect()
    assert connected
    await _drain_connect(communicator)

    await communicator.send_json_to(
        {
            "type": "connection_waypoints_updated",
            "connection_id": 7,
            "waypoints": [{"x": 1.0, "y": 2.0}],
            "list_key": "edge_list",
            "editor": editor_payload(viewer_member),
        }
    )

    rejection = await communicator.receive_json_from()
    assert rejection["type"] == "op_rejected"
    assert rejection["op_type"] == "connection_waypoints_updated"
    assert rejection["reason"] == "permission_denied"
    assert rejection["node_ref"] == {"id": 7, "temp_id": None}

    await communicator.disconnect()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_viewer_connection_waypoints_updated_with_temp_id_rejection_reports_node_ref_from_temp_id(
    org_graph, viewer_member
):
    """A rejected `connection_waypoints_updated` targeting a not-yet-persisted
    connection (str `connection_id` holding the client-side temp_id) must be
    discriminated by type in `_extract_node_ref` and reported as
    `{"id": None, "temp_id": "<temp_id>"}`, not misread as a real int id."""
    communicator = _make_communicator(org_graph.pk, viewer_member)
    connected, _ = await communicator.connect()
    assert connected
    await _drain_connect(communicator)

    await communicator.send_json_to(
        {
            "type": "connection_waypoints_updated",
            "connection_id": "con-temp-1",
            "waypoints": [{"x": 1.0, "y": 2.0}],
            "list_key": "edge_list",
            "editor": editor_payload(viewer_member),
        }
    )

    rejection = await communicator.receive_json_from()
    assert rejection["type"] == "op_rejected"
    assert rejection["op_type"] == "connection_waypoints_updated"
    assert rejection["reason"] == "permission_denied"
    assert rejection["node_ref"] == {"id": None, "temp_id": "con-temp-1"}

    await communicator.disconnect()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_viewer_nodes_deleted_rejection_reports_node_ref_from_first_ref(
    org_graph, viewer_member
):
    """A rejected bulk `nodes_deleted` must build `node_ref` from the first
    entry of `.refs`, same as the `connections_deleted` bulk case."""
    communicator = _make_communicator(org_graph.pk, viewer_member)
    connected, _ = await communicator.connect()
    assert connected
    await _drain_connect(communicator)

    await communicator.send_json_to(
        {
            "type": "nodes_deleted",
            "refs": [
                {"list_key": "subgraph_node_list", "temp_id": "n-ghost"},
            ],
            "editor": editor_payload(viewer_member),
        }
    )

    rejection = await communicator.receive_json_from()
    assert rejection["type"] == "op_rejected"
    assert rejection["op_type"] == "nodes_deleted"
    assert rejection["reason"] == "permission_denied"
    assert rejection["node_ref"] == {"id": None, "temp_id": "n-ghost"}

    await communicator.disconnect()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_viewer_node_locked_is_rejected_and_no_lock_granted(
    org_graph, viewer_member
):
    """A connected Viewer sending node_locked must receive an ErrorMessage
    (not an OpRejectedMessage — locking doesn't fit that shape), and no lock
    may actually be granted in lock_service."""
    communicator = _make_communicator(org_graph.pk, viewer_member)
    connected, _ = await communicator.connect()
    assert connected
    await _drain_connect(communicator)

    await communicator.send_json_to(
        {
            "type": "node_locked",
            "node_id": "node-1",
            "field": "label",
            "editor": editor_payload(viewer_member),
        }
    )

    rejection = await communicator.receive_json_from()
    assert rejection["type"] == "error"
    assert rejection["code"] == "permission_denied"

    assert _ls_module.lock_service.get_holder(org_graph.pk, "node-1", "label") is None

    await communicator.disconnect()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_viewer_cursor_moved_still_relays(
    org_graph, viewer_member, member_member, fake_cursor_redis_for_permission_tests
):
    """cursor_moved never mutates state, so it must relay normally regardless
    of permission level — the read-only gate must not overreach into
    presence/cursor traffic."""

    comm_viewer, comm_member = await connect_pair(
        org_graph, viewer_member, member_member
    )

    await comm_viewer.send_json_to(
        {
            "type": "cursor_moved",
            "x": 10.0,
            "y": 20.0,
            "editor": editor_payload(viewer_member),
        }
    )

    await asyncio.sleep(CURSOR_FLUSH_INTERVAL_SECONDS * 2)

    msg = await comm_member.receive_json_from()
    assert msg["type"] == "cursor_batch"
    cursors = msg["cursors"]
    assert len(cursors) == 1
    assert cursors[0]["x"] == 10.0
    assert cursors[0]["y"] == 20.0
    assert cursors[0]["editor"]["user_id"] == viewer_member.pk

    await comm_viewer.disconnect()
    await comm_member.disconnect()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_downgraded_member_first_write_after_downgrade_is_rejected(
    org_graph, default_org, member_member, viewer_role, superadmin_user
):
    """Explicitly proves the cached bitmask is refreshed and actually used —
    not just checked once at connect() time. member_member connects with
    UPDATE, successfully creates a node, is then downgraded to Viewer, and
    their very next write (not merely "some write, eventually") is rejected."""
    communicator = _make_communicator(org_graph.pk, member_member)
    connected, _ = await communicator.connect()
    assert connected
    await _drain_connect(communicator)

    # Pre-downgrade write succeeds (no rejection observed).
    await communicator.send_json_to(
        {
            "type": "node_created",
            "node": {"temp_id": "n1", "node_name": "Node A"},
            "list_key": "python_node_list",
            "editor": editor_payload(member_member),
        }
    )
    assert await communicator.receive_nothing(timeout=0.3)

    service = MembershipManagementService()
    await sync_to_async(service.change_role)(
        actor=superadmin_user,
        membership_id=await _membership_id(member_member, default_org),
        role_id=viewer_role.id,
    )
    rights_changed = await communicator.receive_json_from()
    assert rights_changed["type"] == "edit_rights_changed"
    assert rights_changed["can_edit"] is False

    # First write after the downgrade must be rejected.
    await communicator.send_json_to(
        {
            "type": "node_updated",
            "node": {"temp_id": "n1", "node_name": "Node A Renamed"},
            "list_key": "python_node_list",
            "changed_fields": ["node_name"],
            "op_id": "first-write-after-downgrade",
            "editor": editor_payload(member_member),
        }
    )
    rejection = await communicator.receive_json_from()
    assert rejection["type"] == "op_rejected"
    assert rejection["op_id"] == "first-write-after-downgrade"
    assert rejection["reason"] == "permission_denied"

    await communicator.disconnect()


# ---------------------------------------------------------------------------
# op_rejected on every denied write: BE-side rejection is a defense-in-depth
# safety net (the FE is expected to block the canvas entirely for users
# without edit rights), so it must fire every time a denied write is
# attempted — not just once per "episode".
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_downgraded_connection_all_three_writes_are_rejected(
    org_graph, default_org, member_member, viewer_role, superadmin_user
):
    """member_member is downgraded to Viewer, then fires 3 state-mutating ops
    in a row. Every single one must produce its own op_rejected message — no
    throttling — and all three ops must still have been blocked from ever
    reaching apply_op (snapshot unchanged)."""
    communicator = _make_communicator(org_graph.pk, member_member)
    connected, _ = await communicator.connect()
    assert connected
    await _drain_connect(communicator)

    service = MembershipManagementService()
    await sync_to_async(service.change_role)(
        actor=superadmin_user,
        membership_id=await _membership_id(member_member, default_org),
        role_id=viewer_role.id,
    )
    rights_changed = await communicator.receive_json_from()
    assert rights_changed["type"] == "edit_rights_changed"
    assert rights_changed["can_edit"] is False

    for index in range(3):
        await communicator.send_json_to(
            {
                "type": "node_created",
                "node": {"temp_id": f"n{index}", "node_name": f"Node {index}"},
                "list_key": "python_node_list",
                "editor": editor_payload(member_member),
            }
        )
        rejection = await communicator.receive_json_from()
        assert rejection["type"] == "op_rejected"
        assert rejection["reason"] == "permission_denied"

    snapshot = await _gss_module.graph_state_service.get_snapshot(org_graph.pk)
    assert snapshot is not None
    assert snapshot["python_node_list"] == []

    await communicator.disconnect()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_recheck_with_no_actual_change_sends_no_edit_rights_changed(
    org_graph, default_org, member_member
):
    """A `permission_changed` broadcast that triggers a recheck but reflects
    no actual change to the connected user's permissions (nothing was
    mutated in the DB) must not push a spurious `edit_rights_changed`."""
    communicator = _make_communicator(org_graph.pk, member_member)
    connected, _ = await communicator.connect()
    assert connected
    await _drain_connect(communicator)

    from channels.layers import get_channel_layer

    from tables.graph_collab.groups import org_group_name

    channel_layer = get_channel_layer()
    await channel_layer.group_send(
        org_group_name(default_org.id),
        {"type": "permission_changed", "user_id": member_member.id},
    )

    assert await communicator.receive_nothing(timeout=0.3)
    await communicator.disconnect()


# ---------------------------------------------------------------------------
# Org-wide group membership: the socket also joins `org_{org_id}` (in
# addition to the per-graph `graph_edit_{graph_id}` group) on connect, and
# leaves it on disconnect.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_connect_joins_org_group_and_relays_org_broadcast(
    org,
    isolated_org_graph,
    test_user,
    grant_test_user_membership_in_org,
    make_communicator,
):
    communicator = make_communicator(isolated_org_graph.pk, test_user)
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
    org,
    other_org,
    isolated_org_graph,
    test_user,
    grant_test_user_membership_in_org,
    make_communicator,
):
    communicator = make_communicator(isolated_org_graph.pk, test_user)
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
    org,
    isolated_org_graph,
    test_user,
    grant_test_user_membership_in_org,
    make_communicator,
):
    communicator = make_communicator(isolated_org_graph.pk, test_user)
    connected, _ = await communicator.connect()
    assert connected
    await _drain_connect(communicator)
    await communicator.disconnect()

    channel_layer = get_channel_layer()
    org_group_channels = channel_layer.groups.get(f"org_{org.id}", {})
    assert org_group_channels == {}


# ---------------------------------------------------------------------------
# User-wide access changes: sent to the per-user `graph_edit_user_{user_id}` group, so
# they reach the socket even when the user has no membership in any org.
# ---------------------------------------------------------------------------


_ACCESS_CHANGED_REASON = "Your access to this flow has changed. Please reconnect."


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_revoke_superadmin_without_memberships_closes_socket(org_graph, superadmin_user):
    """The real superadmin case: no membership row anywhere, so no org group
    names this user. Only the user group can deliver the recheck, and with
    the bypass gone the user has no access at all."""
    target = await sync_to_async(get_user_model().objects.create_superuser)(
        email="membershipless-superadmin@example.com",
        password="TestPass123!",
    )
    communicator = _connect_session(org_graph.pk, target)

    await sync_to_async(UserManagementService().revoke_superadmin)(
        actor=superadmin_user, target_user_id=target.id
    )

    response = await _receive_close(communicator)
    assert response["type"] == "websocket.close"
    assert response["code"] == 4403
    assert response["reason"] == _ACCESS_CHANGED_REASON
    await communicator.disconnect()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_deactivate_user_closes_socket(org_graph, member_member, superadmin_user):

    communicator = _connect_session(org_graph.pk, member_member)

    await sync_to_async(UserManagementService().set_user_active)(
        actor=superadmin_user, target_user_id=member_member.id, value=False
    )

    response = await _receive_close(communicator)
    assert response["type"] == "websocket.close"
    assert response["code"] == 4403
    assert response["reason"] == _ACCESS_CHANGED_REASON
    await communicator.disconnect()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_delete_user_closes_socket(org_graph, member_member, superadmin_user):

    communicator = _connect_session(org_graph.pk, member_member)

    await sync_to_async(UserManagementService().delete_user)(
        actor=superadmin_user,
        target_user_id=member_member.id,
        verification_phrase=f"delete-{member_member.email}",
    )

    response = await _receive_close(communicator)
    assert response["type"] == "websocket.close"
    assert response["code"] == 4403
    assert response["reason"] == _ACCESS_CHANGED_REASON
    await communicator.disconnect()


@sync_to_async
def _custom_role_holder(org, email, bitmask):
    role = Role.objects.create(name=f"custom-{email}", org=org, is_built_in=False)
    RolePermission.objects.create(
        role=role, resource_type=ResourceType.FLOWS, permissions=bitmask
    )
    user = get_user_model().objects.create_user(email=email, password="TestPass123!")
    OrganizationUser.objects.create(user=user, org=org, role=role)
    return role, user


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_custom_role_update_dropping_update_sends_edit_rights_changed(
    org_graph, default_org, superadmin_user
):
    role, holder = await _custom_role_holder(
        default_org, "custom-role-holder@example.com", Permission.READ | Permission.UPDATE
    )
    communicator = _connect_session(org_graph.pk, holder)
   

    await sync_to_async(RoleManagementService().update_role)(
        actor=superadmin_user,
        role_id=role.id,
        changes={
            "permissions": [
                {"resource_type": ResourceType.FLOWS.value, "bitmask": int(Permission.READ)}
            ]
        },
    )

    rights_changed = await communicator.receive_json_from()
    assert rights_changed["type"] == "edit_rights_changed"
    assert rights_changed["can_edit"] is False
    assert await communicator.receive_nothing(timeout=0.3)
    await communicator.disconnect()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_connect_joins_and_disconnect_discards_user_group(org_graph, member_member):
    communicator = _connect_session(org_graph.pk, member_member)

    channel_layer = get_channel_layer()
    user_group = user_group_name(member_member.id)
    assert len(channel_layer.groups.get(user_group, {})) == 1

    await communicator.disconnect()

    assert channel_layer.groups.get(user_group, {}) == {}


# ---------------------------------------------------------------------------
# One user with live sessions in two orgs: a per-org change reaches only the
# session in that org; a user-wide change reaches both.
# ---------------------------------------------------------------------------


@sync_to_async
def _member_of_two_orgs(org_a, org_b, role):
    """A user holding `role` in both orgs, plus one graph in each org."""
    user = get_user_model().objects.create_user(
        email="two-org-member@example.com", password="TestPass123!"
    )
    OrganizationUser.objects.create(user=user, org=org_a, role=role)
    OrganizationUser.objects.create(user=user, org=org_b, role=role)
    graph_a = Graph.objects.create(name="two-org-graph-a", org=org_a)
    graph_b = Graph.objects.create(name="two-org-graph-b", org=org_b)
    return user, graph_a, graph_b


async def _deactivate_organization(actor, user, org):
    await sync_to_async(OrganizationManagementService().deactivate_organization)(org_id=org.id)


async def _remove_membership(actor, user, org):
    await sync_to_async(MembershipManagementService().remove_member)(
        actor=actor, membership_id=await _membership_id(user, org)
    )


@pytest.mark.parametrize(
    "remove_access_in_org",
    [
        pytest.param(_deactivate_organization, id="deactivate-org"),
        pytest.param(_remove_membership, id="remove-membership"),
    ],
)
@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_access_loss_in_one_org_closes_only_that_orgs_session(
    remove_access_in_org, org, other_org, member_role, viewer_role, superadmin_user
):
    """`org` (A) loses the user; `other_org` (B) keeps them. `other_org`
    stays active, so deactivating A never hits the last-active-org guard.

    A recheck of an unchanged session sends nothing, so `receive_nothing` on
    B alone could not tell "not rechecked" from "rechecked, no change". The
    user is therefore demoted in B with a raw update (no signal) first: any
    recheck of B would now send `edit_rights_changed`. The final
    group_send shows that this probe does fire when B really is rechecked."""
    user, graph_a, graph_b = await _member_of_two_orgs(org, other_org, member_role)
    session_a = await _connect_session(graph_a.pk, user)
    session_b = await _connect_session(graph_b.pk, user)
    await sync_to_async(
        OrganizationUser.objects.filter(user=user, org=other_org).update
    )(role=viewer_role)

    await remove_access_in_org(superadmin_user, user, org)

    response = await _receive_close(session_a)
    assert response["type"] == "websocket.close"
    assert response["code"] == 4403
    assert response["reason"] == _ACCESS_CHANGED_REASON
    assert await session_b.receive_nothing(timeout=0.3)

    await get_channel_layer().group_send(
        org_group_name(other_org.id), {"type": "permission_changed", "user_id": user.id}
    )
    rights_changed = await session_b.receive_json_from()
    assert rights_changed["type"] == "edit_rights_changed"
    assert rights_changed["can_edit"] is False

    await session_a.disconnect()
    await session_b.disconnect()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_delete_user_closes_sessions_in_every_org(
    org, other_org, member_role, superadmin_user
):
    user, graph_a, graph_b = await _member_of_two_orgs(org, other_org, member_role)
    sessions = [
        await _connect_session(graph_a.pk, user),
        await _connect_session(graph_b.pk, user),
    ]

    await sync_to_async(UserManagementService().delete_user)(
        actor=superadmin_user,
        target_user_id=user.id,
        verification_phrase=f"delete-{user.email}",
    )

    for session in sessions:
        response = await _receive_close(session)
        assert response["type"] == "websocket.close"
        assert response["code"] == 4403
        assert response["reason"] == _ACCESS_CHANGED_REASON
        await session.disconnect()
