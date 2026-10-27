"""Person-only surfaces refuse a plugin's service account and keep working for people."""

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken
from tables.models import Graph
from tables.models.mcp_models import McpTool
from tables.models.python_models import PythonCode, PythonCodeTool

from tests.plugins_tests.conftest import service_account_client

pytestmark = [pytest.mark.django_db]

PLUGIN_REFUSAL = "Plugin service accounts cannot use this endpoint."
# Enough declared access that only the person-only gate can be what refuses.
BROAD_ACCESS = [
    {"resource_type": "flows", "actions": ["read", "create", "update", "use"], "reason": "Flows."},
    {"resource_type": "tools", "actions": ["read", "create", "update"], "reason": "Tools."},
    {"resource_type": "voice", "actions": ["read", "create"], "reason": "Voice."},
]


@pytest.fixture
def plugin_client(weather_backend, service_account_key, acme):
    plugin = weather_backend(access=BROAD_ACCESS)
    return service_account_client(service_account_key(plugin, acme), acme)


@pytest.fixture
def person_client(admin_acme, acme):
    client = APIClient()
    client.credentials(
        HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(admin_acme).access_token}", HTTP_X_ORGANIZATION_ID=str(acme.pk)
    )
    return client


@pytest.fixture
def surfaces(acme):
    """(name, method, url, body) of each person-only surface, with what it acts on."""
    graph = Graph.objects.create(name="Assisted flow", org=acme)
    python_tool = PythonCodeTool.objects.create(
        name="tool", description="", python_code=PythonCode.objects.create(code="x", entrypoint="main"), org=acme
    )
    mcp_tool = McpTool.objects.create(name="mcp-tool", transport="https://example.com", tool_name="do_thing", org=acme)
    flow_assistant = f"/api/flow-assistants/{graph.pk}/"
    conversation = f"{flow_assistant}conversations/1/"
    return [
        ("audit presets list", "get", "/api/audit-filter-presets/", None),
        ("audit presets create", "post", "/api/audit-filter-presets/", {"name": "Mine", "filters": {}}),
        ("python tool favorite", "post", f"/api/python-code-tool/{python_tool.pk}/favorite/", None),
        ("mcp tool favorite", "post", f"/api/mcp-tools/{mcp_tool.pk}/favorite/", None),
        ("flow assistant config", "get", flow_assistant, None),
        ("flow assistant conversations", "get", f"{flow_assistant}conversations/", None),
        ("flow assistant conversation", "get", conversation, None),
        ("flow assistant message", "post", f"{conversation}messages/", {"content": "hi"}),
        ("flow assistant cancel", "post", f"{conversation}cancel/", None),
        ("flow assistant audit", "get", "/api/flow-assistants/audit/conversations/", None),
        ("realtime init", "post", "/api/init-realtime/", {}),
        ("notify email", "post", "/api/notify/email/", {"to": "someone@example.com", "subject": "s", "body": "b"}),
    ]


def test_every_person_only_surface_refuses_a_service_account(plugin_client, surfaces):
    for name, method, url, body in surfaces:
        response = getattr(plugin_client, method)(url, body, format="json")

        assert response.status_code == 403, (name, response.status_code, response.content)
        assert response.json() == {"status_code": 403, "code": "permission_denied", "message": PLUGIN_REFUSAL}, name


def test_the_flow_assistant_stream_never_reads_a_plugin_key(plugin_client, acme):
    graph = Graph.objects.create(name="Streamed", org=acme)

    response = plugin_client.get(f"/api/flow-assistants/{graph.pk}/conversations/1/stream/")

    assert response.status_code == 401
    assert response.json()["code"] == "invalid_sse_ticket"


def test_a_person_is_not_refused_by_the_gate(person_client, surfaces):
    for name, method, url, body in surfaces:
        response = getattr(person_client, method)(url, body, format="json")

        refused_by_gate = response.status_code == 403 and response.json().get("message") == PLUGIN_REFUSAL
        assert not refused_by_gate, name


def test_a_person_still_lists_and_favorites(person_client, surfaces):
    by_name = {name: (method, url, body) for name, method, url, body in surfaces}

    for name, expected in (("audit presets list", 200), ("python tool favorite", 201), ("mcp tool favorite", 201)):
        method, url, body = by_name[name]
        assert getattr(person_client, method)(url, body, format="json").status_code in (expected, 200, 204), name
