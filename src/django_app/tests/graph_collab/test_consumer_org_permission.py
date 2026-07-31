"""
Regression tests for GraphEditConsumer.connect() org-membership + flows-access
gating, plus the live-session revocation follow-up: a user demoted or removed
from an org (or globally stripped of superadmin) has their live collab socket
kept in sync with their current access, instead of it silently keeping
whatever access level they had when they connected.

Root cause (connect()-time gap): connect() authenticated the WS ticket but never
checked whether the authenticated user is a member of the graph's org, nor
whether their role grants any flows access. Any authenticated user could open
a collab session on ANY graph_id, including graphs belonging to other
organizations, and both read and mutate its live snapshot.

The fix resolves `EffectivePermissions` for (user, org) right after `org_id`
is resolved and before `accept()`, requiring at least `Permission.READ` on
`ResourceType.FLOWS` to connect at all. A connection that lacks
`Permission.UPDATE` (e.g. the built-in Viewer role) connects successfully in
a **read-only** capacity — it sees live cursors/edits/presence, but every
state-mutating message (`_STATE_OP_TYPES` via `_handle_relay`, plus
`node_locked`/`node_unlocked`) is rejected server-side rather than applied.

Root cause (live-session gap): once connected, access was never re-checked,
so a demotion/removal/superadmin-revocation had no effect on an already-open
socket until the browser reloaded. The fix broadcasts `permission_changed`
(org-wide) from the three RBAC mutation paths, and the consumer both reacts
to that broadcast and re-checks on a periodic backstop timer, refreshing its
cached permission bitmask in place — closing with 4403 only on a genuine
loss of ALL access (no membership at all, or the org deactivated).

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

Live-session access changes:
7. `change_role` downgrading a connected Member to Viewer (loses UPDATE,
   keeps READ) does NOT disconnect them — it downgrades them to read-only,
   verified by a subsequent write attempt being rejected.
8. `remove_membership` on a connected user closes their socket with 4403
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
"""

import asyncio

import pytest

from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model

from tables.graph_collab import graph_state_service as _gss_module
from tables.graph_collab import lock_service as _ls_module
from tables.graph_collab.constants import CURSOR_FLUSH_INTERVAL_SECONDS
from tables.models import Graph, Organization
from tables.models.rbac_models import OrganizationUser, Role
from tables.services.rbac.organization_management_service import (
    OrganizationManagementService,
)
from tables.services.rbac.user_management_service import UserManagementService

from tests.graph_collab.conftest import _make_communicator, _drain_connect


async def _connect_raw(communicator, timeout: float = 1.0) -> dict:
    """Trigger a WS connect and return the raw ASGI response message
    (unlike ``communicator.connect()``, this preserves the ``reason`` key
    on a ``websocket.close`` response)."""
    await communicator.send_input({"type": "websocket.connect"})
    return await communicator.receive_output(timeout)


async def _receive_close(communicator, timeout: float = 1.0) -> dict:
    """Wait for the server to close the socket and return the raw
    ``websocket.close`` ASGI message (code + optional reason)."""
    return await communicator.receive_output(timeout)


@pytest.fixture
def other_org(db):
    return Organization.objects.create(name="Other Organization")


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
async def test_connect_superadmin_bypasses_org_membership(org_graph, superadmin_user):
    """Superadmin has no membership row in default_org at all, but the
    platform-wide bypass in PermissionResolver must still grant access."""
    communicator = _make_communicator(org_graph.pk, superadmin_user)
    connected, _ = await communicator.connect()
    assert connected
    await _drain_connect(communicator)
    await communicator.disconnect()


# ---------------------------------------------------------------------------
# Live-session revocation: change_role / remove_membership / revoke_superadmin
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

    service = UserManagementService()
    await sync_to_async(service.change_role)(
        actor=superadmin_user,
        org_id=default_org.id,
        user_id=member_member.id,
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

    service = UserManagementService()
    await sync_to_async(service.change_role)(
        actor=superadmin_user,
        org_id=default_org.id,
        user_id=regular_user.id,
        role_id=member_role.id,
    )

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

    service = UserManagementService()
    await sync_to_async(service.remove_membership)(
        actor=superadmin_user,
        org_id=default_org.id,
        user_id=member_member.id,
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
    """The is_superadmin flag is global, not per-org — a superadmin can have
    live collab sessions in several orgs simultaneously. Revoking the flag
    must re-check every one of them against the target's actual per-org role
    — not disconnect them outright.

    ``target`` only holds the Viewer role (has flows READ, lacks UPDATE) in
    both orgs — while superadmin, the platform-wide bypass grants full access
    regardless; once revoked, the Viewer role alone grants exactly enough to
    stay connected read-only. Both connections must stay open, and a write
    attempt on either must be rejected, proving the downgrade is real and not
    masked by residual superadmin access."""
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

    editor_payload = {
        "user_id": target.pk,
        "display_name": "x",
        "avatar_url": None,
    }
    for communicator in (communicator_a, communicator_b):
        await communicator.send_json_to(
            {
                "type": "node_created",
                "node": {"temp_id": "n1", "node_name": "Node A"},
                "list_key": "python_node_list",
                "editor": editor_payload,
            }
        )
        rejection = await communicator.receive_json_from()
        assert rejection["type"] == "op_rejected"
        assert rejection["reason"] == "permission_denied"

    await communicator_a.disconnect()
    await communicator_b.disconnect()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_permission_changed_for_other_user_does_not_disconnect(
    org_graph, default_org, member_member, viewer_role, superadmin_user
):
    """A permission_changed broadcast naming a DIFFERENT user_id on the same
    org group must not affect an unrelated connected user's socket."""
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
# every already-open socket belonging to a member of that org, mirroring the
# per-mutation notify_permission_changed wiring above.
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

    response_b = await _receive_close(communicator_b)
    assert response_b["type"] == "websocket.close"
    assert response_b["code"] == 4403

    await communicator_a.disconnect()
    await communicator_b.disconnect()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_deactivate_organization_does_not_disconnect_other_org_members(
    default_org, other_org, other_org_member
):
    """A member of a DIFFERENT, still-active org must be unaffected when some
    other org gets deactivated — no false-positive disconnect."""
    graph_in_other_org = await sync_to_async(Graph.objects.create)(
        name="deactivate-other-org-graph", org=other_org
    )
    communicator = _make_communicator(graph_in_other_org.pk, other_org_member)
    connected, _ = await communicator.connect()
    assert connected
    await _drain_connect(communicator)

    service = OrganizationManagementService()
    await sync_to_async(service.deactivate_organization)(org_id=default_org.id)

    assert await communicator.receive_nothing(timeout=0.3)
    await communicator.disconnect()


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
            "editor": {
                "user_id": viewer_member.pk,
                "display_name": "x",
                "avatar_url": None,
            },
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
            "editor": {
                "user_id": viewer_member.pk,
                "display_name": "x",
                "avatar_url": None,
            },
        }
    )

    rejection = await communicator.receive_json_from()
    assert rejection["type"] == "error"
    assert rejection["code"] == "permission_denied"

    assert (
        _ls_module.lock_service.get_holder(org_graph.pk, "node-1", "label") is None
    )

    await communicator.disconnect()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_viewer_cursor_moved_still_relays(
    org_graph, viewer_member, member_member, fake_cursor_redis_for_permission_tests
):
    """cursor_moved never mutates state, so it must relay normally regardless
    of permission level — the read-only gate must not overreach into
    presence/cursor traffic."""
    comm_viewer = _make_communicator(org_graph.pk, viewer_member)
    comm_member = _make_communicator(org_graph.pk, member_member)

    await comm_viewer.connect()
    await _drain_connect(comm_viewer)
    await comm_member.connect()
    await comm_viewer.receive_json_from()  # user_joined for member_member
    await _drain_connect(comm_member)

    await comm_viewer.send_json_to(
        {
            "type": "cursor_moved",
            "x": 10.0,
            "y": 20.0,
            "editor": {
                "user_id": viewer_member.pk,
                "display_name": "x",
                "avatar_url": None,
            },
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

    editor_payload = {
        "user_id": member_member.pk,
        "display_name": "x",
        "avatar_url": None,
    }

    # Pre-downgrade write succeeds (no rejection observed).
    await communicator.send_json_to(
        {
            "type": "node_created",
            "node": {"temp_id": "n1", "node_name": "Node A"},
            "list_key": "python_node_list",
            "editor": editor_payload,
        }
    )
    assert await communicator.receive_nothing(timeout=0.3)

    service = UserManagementService()
    await sync_to_async(service.change_role)(
        actor=superadmin_user,
        org_id=default_org.id,
        user_id=member_member.id,
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
            "editor": editor_payload,
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

    service = UserManagementService()
    await sync_to_async(service.change_role)(
        actor=superadmin_user,
        org_id=default_org.id,
        user_id=member_member.id,
        role_id=viewer_role.id,
    )
    rights_changed = await communicator.receive_json_from()
    assert rights_changed["type"] == "edit_rights_changed"
    assert rights_changed["can_edit"] is False

    editor_payload = {
        "user_id": member_member.pk,
        "display_name": "x",
        "avatar_url": None,
    }

    for index in range(3):
        await communicator.send_json_to(
            {
                "type": "node_created",
                "node": {"temp_id": f"n{index}", "node_name": f"Node {index}"},
                "list_key": "python_node_list",
                "editor": editor_payload,
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
