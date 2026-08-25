import asyncio
import unittest.mock

import fakeredis
import pytest
import pytest_asyncio
import fakeredis.aioredis

from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.test import override_settings
from django.urls import re_path

from asgiref.sync import sync_to_async

from tables.models import Graph
from tables.models.crew_models import Crew
from tables.models.graph_models import CrewNode
from tables.models.rbac_models import OrganizationUser

from tables.graph_collab import graph_state_service as _gss_module
from tables.graph_collab import lock_service as _ls_module
from tables.graph_collab.constants import _ALL_LIST_KEYS, _LIST_KEY_TO_DELETE_KEY
from tables.graph_collab.consumers import GraphEditConsumer
from tables.graph_collab.flush_service import GraphFlushService
from tables.graph_collab.presence_service import (
    presence_service as _presence_service_singleton,
    GraphPresenceService,
)
from tables.graph_collab.protocol import EditorInfo
from tables.services.graph_bulk_save_service.registry import NODE_TYPE_REGISTRY
from tables.services.schedule_trigger_service import ScheduleTriggerService
from tables.services import redis_service as _rs_module


application = URLRouter(
    [re_path(r"ws/graphs/(?P<graph_id>\d+)/edit/$", GraphEditConsumer.as_asgi())]
)


_active_communicators: list[WebsocketCommunicator] = []


def _make_communicator(graph_id: int, user=None):
    """Build a communicator with scope["user"] pre-set (bypasses ticket middleware)."""
    scope_user = user or AnonymousUser()
    communicator = WebsocketCommunicator(
        application,
        f"ws/graphs/{graph_id}/edit/",
    )
    communicator.scope["user"] = scope_user
    _active_communicators.append(communicator)
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


CHANNEL_LAYERS_OVERRIDE = {
    "default": {
        "BACKEND": "channels.layers.InMemoryChannelLayer",
    }
}


def _editor(user_id: int = 1, name: str = "Alice") -> EditorInfo:
    return EditorInfo(user_id=user_id, display_name=name, avatar_url=None)


def editor_payload(user) -> dict:
    """Wire-format editor dict for op/lock payloads sent from a test client."""
    return {"user_id": user.pk, "display_name": "x", "avatar_url": None}


def _empty_deleted() -> dict:
    """All-empty `deleted` accumulator, derived from the registry so a new
    node/edge type can never silently go missing here."""
    return {delete_key: [] for delete_key in _LIST_KEY_TO_DELETE_KEY.values()}


def _base_snapshot(**overrides) -> dict:
    """Minimal valid superset snapshot for flush tests, derived from the registry."""
    base = {list_key: [] for list_key in _ALL_LIST_KEYS}
    base["save_version"] = 0  # overridden by the service from DB
    base["deleted"] = _empty_deleted()
    base.update(overrides)
    return base


PYTHON_CODE_DATA = {
    "code": "def main(): return 42",
    "entrypoint": "main",
    "libraries": [],
}


async def wait_for(
    condition_coro, timeout: float = 2.0, interval: float = 0.05
) -> bool:
    """Poll `condition_coro()` until it returns truthy or `timeout` elapses."""
    elapsed = 0.0
    while elapsed < timeout:
        if await condition_coro():
            return True
        await asyncio.sleep(interval)
        elapsed += interval
    return False


async def connect_pair(graph, user_a, user_b):
    """Connect two communicators and drain all connect-time messages."""
    comm_a = _make_communicator(graph.pk, user_a)
    comm_b = _make_communicator(graph.pk, user_b)

    await comm_a.connect()
    await _drain_connect(comm_a)

    await comm_b.connect()
    await comm_a.receive_json_from()  # user_joined for user_b
    await _drain_connect(comm_b)

    return comm_a, comm_b


async def receive_or_none(
    communicator, timeout: float = 1.0, poll: float = 0.05
) -> dict | None:
    """Poll a communicator's socket for a message, returning None on timeout.

    Distinct from `wait_for`, which polls a condition coroutine, not a socket.

    The inner `receive_json_from` timeout must always exceed the outer `poll`
    timeout: asgiref's own receive timeout firing cancels the whole consumer
    application task (not just the pending receive), so if the inner timeout
    ever won the race, this would silently kill the consumer instead of just
    reporting "no message yet".
    """
    elapsed = 0.0
    while elapsed < timeout:
        try:
            return await asyncio.wait_for(
                communicator.receive_json_from(timeout=poll * 10), timeout=poll
            )
        except asyncio.TimeoutError:
            elapsed += poll
    return None


async def collect_messages(communicator, timeout: float = 0.5) -> list[dict]:
    """Drain all messages currently queued on `communicator`, stopping at the first gap.

    The inner `receive_json_from` timeout must always exceed the outer `wait_for`
    timeout: asgiref's own receive timeout firing cancels the whole consumer
    application task (not just the pending receive), so if the inner timeout
    ever won the race, a later `disconnect()` would raise `CancelledError`.
    """
    messages = []
    try:
        while True:
            msg = await asyncio.wait_for(
                communicator.receive_json_from(timeout=timeout * 10), timeout=timeout
            )
            messages.append(msg)
    except asyncio.TimeoutError:
        pass
    return messages


async def apply_create_op(communicator, graph_id: int, user, temp_id: str) -> None:
    """Send a node_created op and wait until that exact node appears in the live snapshot."""
    await communicator.send_json_to(
        {
            "type": "node_created",
            "node": {
                "temp_id": temp_id,
                "graph": graph_id,
                "python_code": PYTHON_CODE_DATA,
            },
            "list_key": "python_node_list",
            "editor": editor_payload(user),
        }
    )

    async def _node_in_snapshot():
        snap = await _gss_module.graph_state_service.get_snapshot(graph_id)
        if snap is None:
            return False
        return any(n.get("temp_id") == temp_id for n in snap["python_node_list"])

    assert await wait_for(_node_in_snapshot), (
        f"Node {temp_id!r} did not appear in snapshot"
    )


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
    _presence_service_singleton._store.clear()
    yield
    _presence_service_singleton._store.clear()


@pytest.fixture(autouse=True)
def reset_lock_store():
    """Reset the module-level lock store between tests to prevent state leakage."""
    _ls_module.lock_service._store.clear()
    yield
    _ls_module.lock_service._store.clear()


@pytest_asyncio.fixture(autouse=True)
async def disconnect_leaked_communicators(
    channel_layer_settings, patch_graph_state_redis
):
    """Safety net for tests whose explicit disconnect is skipped by an earlier failure.

    Drains any communicator registered via `_make_communicator` whose explicit
    `disconnect()` was skipped, by calling `disconnect()` on it here instead.
    """
    _active_communicators.clear()
    yield
    while _active_communicators:
        communicator = _active_communicators.pop()
        try:
            await asyncio.wait_for(communicator.disconnect(), timeout=1.0)
        except (Exception, asyncio.CancelledError):
            # Cleanup net only: an already-closed communicator reaching teardown
            # is the normal case, and this must never itself fail or hang an
            # otherwise-passing test. CancelledError is caught explicitly
            # because it is a BaseException, not an Exception — letting it
            # escape here aborts every remaining finalizer for the test,
            # including pytest-django's table truncation, poisoning every
            # later test.
            pass


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


@pytest.fixture
def patch_redis_service(fake_async_redis, monkeypatch):
    """Replace RedisService's async client with the shared `fake_async_redis` instance.

    Not autouse: opt in explicitly for tests that exercise RedisService directly
    (e.g. autosave/flush broadcast tests), so they share the same fake Redis
    instance as `patch_graph_state_redis` instead of each patching in a separate one.
    """
    monkeypatch.setattr(
        type(_rs_module.RedisService()),
        "async_redis_client",
        property(lambda self: fake_async_redis),
    )


@pytest.fixture
def noop_content_hash_refresh(monkeypatch):
    """Patch out the content_hash DB refresh step so a DB-free test file stays DB-free.

    Not autouse: must be opted into explicitly, since test_content_hash_refresh.py
    tests this exact function and a directory-wide autouse patch would neuter it.
    """

    async def _noop(snapshot):
        return None

    monkeypatch.setattr(_gss_module, "_refresh_flushed_content_hashes", _noop)


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
    return _make_communicator


@pytest.fixture
def presence_service():
    """Fresh GraphPresenceService instance for unit tests."""
    return GraphPresenceService()


@pytest.fixture
def live_state_service():
    return _gss_module.GraphLiveStateService()


@pytest.fixture
def base_snapshot():
    """Factory for a minimal valid bulk-save-shape snapshot.

    Usage: ``base_snapshot(crew_node_list=[...], save_version=graph.save_version)``.
    """
    return _base_snapshot


@pytest.fixture
def empty_deleted():
    """Factory for an all-empty `deleted` accumulator. Usage: ``empty_deleted()``."""
    return _empty_deleted


@pytest.fixture
def editor() -> EditorInfo:
    """A single default EditorInfo for partial-update/op tests."""
    return _editor(name="Test")


@pytest.fixture
def flush_service():
    """Fresh GraphFlushService instance — the service holds no state, so a new
    instance per test is equivalent to the module-level singleton."""
    return GraphFlushService()


@pytest.fixture
def schedule_trigger_service():
    """ScheduleTriggerService is a SingletonMeta singleton already constructed
    at Django app startup (tables/apps.py). Any constructor args passed here
    are silently ignored — SingletonMeta only runs ``__init__`` on the very
    first construction in the process, so this always returns that
    pre-existing app-startup instance, wired with its own real
    SessionManagerService. Tests only need a working service, not an
    injected one, so returning the singleton as-is is sufficient.
    """
    return ScheduleTriggerService()


def _model_for(list_key: str):
    return next(c.model_class for c in NODE_TYPE_REGISTRY if c.list_key == list_key)


@sync_to_async
def count_nodes(list_key: str, graph_id: int) -> int:
    return _model_for(list_key).objects.filter(graph_id=graph_id).count()


@sync_to_async
def get_node(list_key: str, node_id: int):
    return _model_for(list_key).objects.get(pk=node_id)


@sync_to_async
def first_node(list_key: str, graph_id: int):
    return _model_for(list_key).objects.filter(graph_id=graph_id).first()


@sync_to_async
def get_graph_save_version(graph_id: int) -> int:
    return Graph.objects.get(pk=graph_id).save_version


@sync_to_async
def _create_start_node(graph):
    """Create a StartNode row for the given graph and return it."""
    from tables.models.graph_models import StartNode

    return StartNode.objects.create(
        graph=graph,
        variables={"variables": {"greeting": "hello"}, "persistent": {}},
    )


@sync_to_async
def _create_end_node(graph):
    """Create an EndNode row for the given graph and return it."""
    from tables.models.graph_models import EndNode

    return EndNode.objects.create(
        graph=graph,
        output_map={"context": "variables"},
    )


@pytest.fixture
def make_crew_node():
    """Async factory creating an org-scoped Crew and, optionally, a CrewNode.

    Usage: ``crew, node = await make_crew_node(default_org, graph=test_graph)``.
    Pass ``graph=None`` (the default) to create just the Crew.
    """

    @sync_to_async
    def _make(
        org,
        graph=None,
        crew_name: str = "Test Crew",
        node_name: str = "Crew-Node #1",
    ) -> tuple[Crew, CrewNode | None]:
        crew = Crew.objects.create(name=crew_name, org=org)
        node = None
        if graph is not None:
            node = CrewNode.objects.create(graph=graph, node_name=node_name, crew=crew)
        return crew, node

    return _make
