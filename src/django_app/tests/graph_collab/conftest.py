import unittest.mock

import fakeredis
import pytest
import fakeredis.aioredis

from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.test import override_settings
from django.urls import re_path

from tables.models import Graph
from tables.models.rbac_models import OrganizationUser

from tables.graph_collab import graph_state_service as _gss_module
from tables.graph_collab import lock_service as _ls_module
from tables.graph_collab.consumers import GraphEditConsumer
from tables.graph_collab.presence_service import presence_service, GraphPresenceService
from tables.graph_collab.protocol import EditorInfo


application = URLRouter(
    [re_path(r"ws/graphs/(?P<graph_id>\d+)/edit/$", GraphEditConsumer.as_asgi())]
)


def _make_communicator(graph_id: int, user=None):
    """Build a communicator with scope["user"] pre-set (bypasses ticket middleware)."""
    scope_user = user or AnonymousUser()
    communicator = WebsocketCommunicator(
        application,
        f"ws/graphs/{graph_id}/edit/",
    )
    communicator.scope["user"] = scope_user
    return communicator


async def _drain_connect(communicator) -> None:
    """Consume the initial messages sent on connect:
    1. presence_state
    2. graph_state (server seeds from DB on every connect)
    3. user_joined (self)
    """
    messages = {(await communicator.receive_json_from())["type"] for _ in range(3)}
    assert "presence_state" in messages
    assert "user_joined" in messages
    assert "graph_state" in messages


async def _drain_connect_with_locks(communicator) -> dict:
    """Consume 4 initial messages when locks are active; return the lock_state message."""
    received = {}
    for _ in range(4):
        msg = await communicator.receive_json_from()
        received[msg["type"]] = msg
    assert "presence_state" in received
    assert "user_joined" in received
    assert "graph_state" in received
    assert "lock_state" in received
    return received["lock_state"]


CHANNEL_LAYERS_OVERRIDE = {
    "default": {
        "BACKEND": "channels.layers.InMemoryChannelLayer",
    }
}


def _editor(user_id: int = 1, name: str = "Alice") -> EditorInfo:
    return EditorInfo(user_id=user_id, display_name=name, avatar_url=None)


def _flow(**lists) -> dict:
    """Return a minimal superset-snapshot dict"""
    base = {
        "crew_node_list": [],
        "python_node_list": [],
        "edge_list": [],
        "conditional_edge_list": [],
    }
    base.update(lists)
    return base


@pytest.fixture(autouse=True)
def channel_layer_settings():
    """Override channel layers so each test gets a fresh in-memory layer."""
    with override_settings(CHANNEL_LAYERS=CHANNEL_LAYERS_OVERRIDE):
        yield


@pytest.fixture
def test_graph(default_org):
    return Graph.objects.create(name="test-graph-collab", org=default_org)


@pytest.fixture
def test_user(db, default_org, org_admin_role):
    """A member of `default_org` with Org Admin rights (flows UPDATE), so the
    consumer's org-membership + FLOWS.UPDATE gate in connect() lets it in on
    `test_graph`/`second_graph`, both seeded in `default_org`."""
    User = get_user_model()
    user = User.objects.create_user(
        email="collab@example.com",
        password="TestPass123!",
        display_name="Collab User",
    )
    OrganizationUser.objects.create(user=user, org=default_org, role=org_admin_role)
    return user


@pytest.fixture
def second_user(db, default_org, org_admin_role):
    """A second member of `default_org` with Org Admin rights, mirroring
    `test_user` — used by multi-connection tests on the same graph."""
    User = get_user_model()
    user = User.objects.create_user(
        email="collab2@example.com",
        password="TestPass123!",
        display_name="Second User",
    )
    OrganizationUser.objects.create(user=user, org=default_org, role=org_admin_role)
    return user


@pytest.fixture
def second_graph(default_org):
    return Graph.objects.create(name="test-graph-collab-2", org=default_org)


@pytest.fixture
def org_graph(default_org):
    return Graph.objects.create(name="org-scoped-graph", org=default_org)


@pytest.fixture
def fake_redis():
    fake = fakeredis.FakeStrictRedis()
    with unittest.mock.patch(
        "tables.services.rbac.ticket_service.get_redis_connection",
        return_value=fake,
    ):
        yield fake


@pytest.fixture(autouse=True)
def reset_presence_store():
    """Reset the module-level presence store between tests to prevent state leakage."""
    presence_service._store.clear()
    yield
    presence_service._store.clear()


@pytest.fixture(autouse=True)
def reset_lock_store():
    """Reset the module-level lock store between tests to prevent state leakage."""
    _ls_module.lock_service._store.clear()
    yield
    _ls_module.lock_service._store.clear()


@pytest.fixture
def fake_async_redis():
    """Fresh fakeredis async client with decode_responses=True."""
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


@pytest.fixture(autouse=True)
def patch_graph_state_redis(fake_async_redis, monkeypatch):
    """Replace the Redis client used by graph_state_service with an in-memory fake.

    Patching ``_redis`` as a property on the class ensures the singleton's
    ``async_redis_client`` is never consulted, so tests run without a live Redis
    server and with full state isolation between tests.
    """
    monkeypatch.setattr(
        type(_gss_module.graph_state_service),
        "_redis",
        property(lambda self: fake_async_redis),
    )
    _gss_module.graph_state_service._locks.clear()
    _gss_module.graph_state_service._revision.clear()
    _gss_module.graph_state_service._flushed_revision.clear()
    yield
    _gss_module.graph_state_service._locks.clear()
    _gss_module.graph_state_service._revision.clear()
    _gss_module.graph_state_service._flushed_revision.clear()


@pytest.fixture(autouse=True)
def reset_autosave_task():
    import tables.graph_collab.autosave_loop as _al_module

    if _al_module._autosave_task is not None and not _al_module._autosave_task.done():
        _al_module._autosave_task.cancel()
    _al_module._autosave_task = None
    yield
    if _al_module._autosave_task is not None and not _al_module._autosave_task.done():
        _al_module._autosave_task.cancel()
    _al_module._autosave_task = None


@pytest.fixture
def auth_client(api_client, regular_user, default_org):
    """
    Override the global auth_client for graph_collab tests.
    GraphViewSet does not declare authentication_classes, so it inherits the
    empty DEFAULT_AUTHENTICATION_CLASSES from test settings — meaning
    credentials() headers are never processed and request.user stays
    AnonymousUser. force_authenticate bypasses the auth middleware entirely
    and sets request.user directly, which is what these tests need.

    Also sends the active-org header: GraphViewSet is org-scoped and
    resolves the active org via OrgContextService, which requires either a
    URL org_id kwarg or the X-Organization-Id header — omitting it fails
    org-scoped requests (e.g. PUT/PATCH in test_graph_saved_notifications.py)
    with 400 org_context_required. regular_user is an Org Admin member of
    default_org, matching the shared `graph` fixture (tests/fixtures.py) and
    this file's own `test_graph`/`second_graph`, both created in default_org.
    """
    api_client.force_authenticate(user=regular_user)
    api_client.credentials(HTTP_X_ORGANIZATION_ID=str(default_org.id))
    return api_client


@pytest.fixture
def make_communicator():
    from django.contrib.auth.models import AnonymousUser

    def _make(graph_id: int, user=None):
        communicator = WebsocketCommunicator(application, f"ws/graphs/{graph_id}/edit/")
        communicator.scope["user"] = user or AnonymousUser()
        return communicator

    return _make


@pytest.fixture
def service():
    """GraphPresenceService instance for unit tests."""
    return GraphPresenceService()


@pytest.fixture
def live_state_service():
    return _gss_module.GraphLiveStateService()
