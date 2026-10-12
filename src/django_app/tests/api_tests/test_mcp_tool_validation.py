import pytest

from tables.models.mcp_models import McpTool
from tables.services.secrets import secret_service
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

MCP_TOOLS_URL = "/api/mcp-tools/"


@pytest.fixture
def client(client_as, admin_acme, acme):
    api_client = client_as(admin_acme)
    api_client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
    return api_client


def _payload(**overrides):
    return {
        "name": "mcp-tool",
        "transport": "https://example.com/mcp",
        "tool_name": "search",
        **overrides,
    }


def _assert_invalid(response, field_name):
    assert response.status_code == 400, response.data
    assert response.data["code"] == "invalid"
    assert field_name in response.data["message"]


@pytest.mark.django_db
class TestMcpToolTransport:
    @pytest.mark.parametrize(
        "transport",
        [
            "/x.py",
            "server.js",
            "file:///tmp/a.py",
            "stdio",
            "ftp://example.com/mcp",
            "http://",
            "https:///no-host",
            "http://[::1",
            "HTTPS://example.com/mcp",
            "Http://example.com/mcp",
            "",
            "https://example.com/" + "a" * 2029,
        ],
    )
    def test_non_http_transport_is_rejected(self, client, transport):
        _assert_invalid(client.post(MCP_TOOLS_URL, _payload(transport=transport), format="json"), "transport")
        assert not McpTool.objects.exists()

    @pytest.mark.parametrize(
        "transport",
        [
            "http://mcp-server:8000/sse",
            "https://example.com/mcp",
            "http://localhost/sse",
            "http://[::1]:8000/sse",
            "https://example.com/" + "a" * 2028,
        ],
    )
    def test_http_transport_is_accepted(self, client, transport):
        response = client.post(MCP_TOOLS_URL, _payload(transport=transport), format="json")

        assert response.status_code == 201, response.data
        assert response.data["transport"] == transport

    def test_put_with_non_http_transport_is_rejected(self, client, acme):
        tool = McpTool.objects.create(
            org=acme, name="existing", transport="https://example.com/mcp", tool_name="search"
        )

        response = client.put(
            f"{MCP_TOOLS_URL}{tool.id}/",
            _payload(name="existing", transport="/tmp/a.py"),
            format="json",
        )

        _assert_invalid(response, "transport")
        tool.refresh_from_db()
        assert tool.transport == "https://example.com/mcp"


@pytest.mark.django_db
class TestMcpToolTimeouts:
    @pytest.mark.parametrize(
        "field_name,minimum,maximum", [("timeout", 1, 1800), ("init_timeout", 1, 120)]
    )
    def test_bounds_are_inclusive(self, client, field_name, minimum, maximum):
        for value in (minimum, maximum):
            response = client.post(
                MCP_TOOLS_URL, _payload(name=f"tool-{value}", **{field_name: value}), format="json"
            )

            assert response.status_code == 201, response.data
            assert response.data[field_name] == value

    @pytest.mark.parametrize(
        "field_name,value",
        [
            ("timeout", 0),
            ("timeout", 0.5),
            ("timeout", 1801),
            ("timeout", None),
            ("init_timeout", 0),
            ("init_timeout", 121),
            ("init_timeout", None),
            ("timeout", "nan"),
            ("timeout", "inf"),
            ("timeout", "-inf"),
            ("init_timeout", "nan"),
        ],
    )
    def test_out_of_bounds_or_null_is_rejected(self, client, field_name, value):
        _assert_invalid(
            client.post(MCP_TOOLS_URL, _payload(**{field_name: value}), format="json"), field_name
        )

    def test_omitted_timeouts_take_defaults(self, client):
        response = client.post(MCP_TOOLS_URL, _payload(), format="json")

        assert response.status_code == 201, response.data
        assert response.data["timeout"] == 30
        assert response.data["init_timeout"] == 10


@pytest.mark.django_db
class TestMcpToolName:
    def test_name_over_255_characters_is_rejected(self, client):
        _assert_invalid(client.post(MCP_TOOLS_URL, _payload(name="n" * 256), format="json"), "name")

    def test_name_of_255_characters_is_accepted(self, client):
        response = client.post(MCP_TOOLS_URL, _payload(name="n" * 255), format="json")

        assert response.status_code == 201, response.data

    def test_duplicate_name_in_same_organization_is_rejected(self, client, acme):
        McpTool.objects.create(
            org=acme, name="taken", transport="https://example.com/mcp", tool_name="search"
        )

        _assert_invalid(client.post(MCP_TOOLS_URL, _payload(name="taken"), format="json"), "name")


@pytest.mark.django_db
class TestMcpToolAuthSecret:
    def test_put_with_null_auth_secret_clears_it(self, client, acme):
        secret = secret_service.create(text="token", org=acme, name="MCP_TOKEN")
        tool = McpTool.objects.create(
            org=acme,
            name="with-secret",
            transport="https://example.com/mcp",
            tool_name="search",
            auth_secret=secret,
        )

        response = client.put(
            f"{MCP_TOOLS_URL}{tool.id}/",
            _payload(name="with-secret", auth_secret_id=None, timeout=30, init_timeout=10),
            format="json",
        )

        assert response.status_code == 200, response.data
        tool.refresh_from_db()
        assert tool.auth_secret_id is None

    def test_other_organization_tool_is_not_found(self, client, beta):
        foreign_tool = McpTool.objects.create(
            org=beta, name="foreign", transport="https://example.com/mcp", tool_name="search"
        )

        response = client.put(
            f"{MCP_TOOLS_URL}{foreign_tool.id}/",
            _payload(name="foreign", transport="/tmp/a.py"),
            format="json",
        )

        assert response.status_code == 404
