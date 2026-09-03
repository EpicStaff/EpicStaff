"""Tests that CrewaiMcpToolFactory.create() rejects unsafe transports.

Network calls (fastmcp.Client) are fully mocked — only the SSRF guard logic
is exercised here.
"""

import socket
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.shared.models import McpToolData
from services.crew.mcp_tool_factory import CrewaiMcpToolFactory


def _make_tool_data(transport: str) -> McpToolData:
    return McpToolData(transport=transport, tool_name="some_tool")


def _mock_getaddrinfo(ip: str):
    return patch(
        "src.shared.security.ssrf_guard.socket.getaddrinfo",
        return_value=[(socket.AF_INET, socket.SOCK_STREAM, 0, "", (ip, 80))],
    )


def _mock_unresolvable():
    return patch(
        "src.shared.security.ssrf_guard.socket.getaddrinfo",
        side_effect=socket.gaierror("Name or service not known"),
    )


# ---------------------------------------------------------------------------
# Blocked transports — factory must raise BEFORE connecting
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_blocks_metadata_ip():
    with _mock_getaddrinfo("169.254.169.254"):
        with pytest.raises(ValueError, match="SSRF"):
            await CrewaiMcpToolFactory().create(
                _make_tool_data("http://169.254.169.254/mcp")
            )


@pytest.mark.asyncio
async def test_create_blocks_localhost():
    with _mock_getaddrinfo("127.0.0.1"):
        with pytest.raises(ValueError, match="SSRF"):
            await CrewaiMcpToolFactory().create(
                _make_tool_data("http://localhost/mcp")
            )


@pytest.mark.asyncio
async def test_create_blocks_private_range():
    with _mock_getaddrinfo("10.10.0.50"):
        with pytest.raises(ValueError, match="SSRF"):
            await CrewaiMcpToolFactory().create(
                _make_tool_data("http://internal-service/mcp")
            )


@pytest.mark.asyncio
async def test_create_blocks_file_scheme():
    """file:// must be rejected even without DNS resolution."""
    with pytest.raises(ValueError, match="SSRF"):
        await CrewaiMcpToolFactory().create(
            _make_tool_data("file:///etc/passwd")
        )


@pytest.mark.asyncio
async def test_create_blocks_unresolvable_host():
    with _mock_unresolvable():
        with pytest.raises(ValueError, match="SSRF"):
            await CrewaiMcpToolFactory().create(
                _make_tool_data("http://nonexistent.invalid/mcp")
            )


# ---------------------------------------------------------------------------
# Allowed transport — factory proceeds to connect (Client mocked)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_allows_public_url_and_attempts_connection():
    """With a public URL the guard passes; the factory then calls the MCP client.

    We mock McpTool.get_tool_data() so no real network call is made.
    """
    mock_tool = MagicMock()
    mock_tool.description = "A tool"
    mock_tool.inputSchema = None

    with _mock_getaddrinfo("93.184.216.34"):
        with patch(
            "services.crew.mcp_tool_factory.McpTool.get_tool_data",
            new_callable=AsyncMock,
            return_value=mock_tool,
        ):
            result = await CrewaiMcpToolFactory().create(
                _make_tool_data("https://mcp.public-vendor.io/sse")
            )

    assert result.name == "some_tool"
