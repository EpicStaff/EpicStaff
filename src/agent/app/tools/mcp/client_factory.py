from __future__ import annotations

from urllib.parse import urlparse

from fastmcp import Client
from fastmcp.client.transports import SSETransport, StreamableHttpTransport
from fastmcp.mcp_config import infer_transport_type_from_url

from app.exceptions import McpToolError
from shared.models.tools import McpToolData

_ALLOWED_TRANSPORT_PREFIXES = ("http://", "https://")


class FastMCPClientFactory:
    """Pure Fabrication: builds a fastmcp Client from McpToolData config.

    Wraps the fastmcp library behind a stable interface so the rest of the
    code is not coupled to Client construction details.
    """

    def create(self, data: McpToolData) -> Client:
        """Build a Client over an explicit HTTP transport.

        The transport is re-validated here with the same rule as the Django model
        validator, because rows stored before that validator are never re-checked.
        It is never handed to fastmcp as a raw string: fastmcp would spawn an
        existing .py/.js path as a local process.

        Raises:
            McpToolError: The transport is not an http:// or https:// URL with a host.
        """
        # Only the scheme and host are checked, not private ranges -- accepted, Won't
        # Fix: an operator/member configures this endpoint and what it points at is
        # their responsibility, per design. Don't re-flag as an SSRF gap without new
        # information (e.g. a path letting one org's config affect another org's
        # request). Separate from, and does not close, the risk of trusting the
        # connected server's own description/inputSchema -- see McpToolGateway.
        url = data.transport
        if not self._is_http_url(url):
            raise McpToolError(
                f"MCP tool '{data.tool_name}' has an invalid transport: "
                "it must be an http:// or https:// URL with a host."
            )

        transport_class = (
            SSETransport if infer_transport_type_from_url(url) == "sse" else StreamableHttpTransport
        )
        return Client(
            transport=transport_class(url),
            timeout=data.timeout,
            auth=data.auth or None,
            init_timeout=data.init_timeout,
        )

    @staticmethod
    def _is_http_url(url: str) -> bool:
        if not url.startswith(_ALLOWED_TRANSPORT_PREFIXES):
            return False
        try:
            return bool(urlparse(url).netloc)
        except ValueError:
            return False
