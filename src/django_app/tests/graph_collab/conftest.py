import unittest.mock

import fakeredis
import pytest

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import re_path
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator

from tables.models import Graph
from tables.graph_collab.consumers import GraphEditConsumer
from tables.graph_collab.presence_service import presence_service, GraphPresenceService
from tables.graph_collab.protocol import EditorInfo


application = URLRouter(
    [re_path(r"ws/graphs/(?P<graph_id>\d+)/edit/$", GraphEditConsumer.as_asgi())]
)


CHANNEL_LAYERS_OVERRIDE = {
    "default": {
        "BACKEND": "channels.layers.InMemoryChannelLayer",
    }
}


def _editor(user_id: int, name: str = "Alice") -> EditorInfo:
    return EditorInfo(user_id=user_id, display_name=name, avatar_url=None)


@pytest.fixture(autouse=True)
def channel_layer_settings():
    """Override channel layers so each test gets a fresh in-memory layer."""
    with override_settings(CHANNEL_LAYERS=CHANNEL_LAYERS_OVERRIDE):
        yield


@pytest.fixture
def test_graph(db):
    return Graph.objects.create(name="test-graph-collab")


@pytest.fixture
def test_user(db):
    User = get_user_model()
    return User.objects.create_user(
        email="collab@example.com",
        password="TestPass123!",
        display_name="Collab User",
    )


@pytest.fixture
def second_user(db):
    User = get_user_model()
    return User.objects.create_user(
        email="collab2@example.com",
        password="TestPass123!",
        display_name="Second User",
    )


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


@pytest.fixture
def auth_client(api_client, regular_user):
    """
    Override the global auth_client for graph_collab tests.
    GraphViewSet does not declare authentication_classes, so it inherits the
    empty DEFAULT_AUTHENTICATION_CLASSES from test settings — meaning
    credentials() headers are never processed and request.user stays
    AnonymousUser. force_authenticate bypasses the auth middleware entirely
    and sets request.user directly, which is what these tests need.
    """
    api_client.force_authenticate(user=regular_user)
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
    return GraphPresenceService()
