"""
Tests for FastMCPClientFactory.

Builds real fastmcp Clients; no connection is opened.
"""

from __future__ import annotations

import pytest
from app.exceptions import McpToolError
from app.tools.executors.mcp_tool import McpToolExecutor
from app.tools.mcp.client_factory import FastMCPClientFactory
from app.tools.mcp.gateway import McpToolGateway
from fastmcp.client.auth.bearer import BearerAuth
from fastmcp.client.transports import SSETransport, StreamableHttpTransport
from shared.models.tools import McpToolData


def _data(transport: str, auth: str | None = None) -> McpToolData:
    return McpToolData(transport=transport, tool_name="search", auth=auth)


def test_existing_python_script_path_is_rejected(tmp_path):
    script = tmp_path / "server.py"
    script.write_text("print('pwned')")

    with pytest.raises(McpToolError, match="invalid transport"):
        FastMCPClientFactory().create(_data(str(script)))


@pytest.mark.parametrize(
    "transport",
    [
        "HTTPS://example.com/mcp",
        "Http://example.com/mcp",
        "ftp://example.com/mcp",
        "https://",
        "http:///path-only",
        "http://[::1",
        "",
    ],
)
def test_non_http_url_is_rejected(transport):
    with pytest.raises(McpToolError, match="invalid transport"):
        FastMCPClientFactory().create(_data(transport))


@pytest.mark.parametrize(
    "transport",
    ["http://mcp-server:8000/sse", "https://example.com/sse/", "https://example.com/sse?x=1"],
)
def test_sse_path_builds_sse_transport(transport):
    client = FastMCPClientFactory().create(_data(transport))

    assert isinstance(client.transport, SSETransport)
    assert client.transport.url == transport


@pytest.mark.parametrize(
    "transport",
    ["http://mcp-server:8000/mcp", "https://example.com/", "https://example.com/ssext"],
)
def test_non_sse_path_builds_streamable_http_transport(transport):
    client = FastMCPClientFactory().create(_data(transport))

    assert isinstance(client.transport, StreamableHttpTransport)
    assert client.transport.url == transport


@pytest.mark.parametrize("transport", ["https://example.com/sse", "https://example.com/mcp"])
def test_auth_is_applied_as_bearer_token(transport):
    client = FastMCPClientFactory().create(_data(transport, auth="secret-token"))

    assert isinstance(client.transport.auth, BearerAuth)
    assert client.transport.auth.token.get_secret_value() == "secret-token"


@pytest.mark.parametrize("auth", [None, ""])
def test_missing_auth_leaves_transport_unauthenticated(auth):
    client = FastMCPClientFactory().create(_data("https://example.com/mcp", auth=auth))

    assert client.transport.auth is None


def test_timeouts_are_passed_to_client():
    data = McpToolData(
        transport="https://example.com/mcp", tool_name="search", timeout=12, init_timeout=3
    )

    client = FastMCPClientFactory().create(data)

    assert client._session_kwargs["read_timeout_seconds"].total_seconds() == 12
    assert client._init_timeout == 3


async def test_rejected_transport_surfaces_as_tool_error_result(tmp_path):
    script = tmp_path / "server.py"
    script.write_text("print('pwned')")
    executor = McpToolExecutor(
        McpToolGateway(FastMCPClientFactory()), _data(str(script)), name="search"
    )

    result = await executor({})

    assert result.is_error is True
    assert "invalid transport" in result.content
