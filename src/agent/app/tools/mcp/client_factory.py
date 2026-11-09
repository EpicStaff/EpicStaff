from __future__ import annotations

from urllib.parse import unquote, urlparse, urlsplit, urlunsplit

import httpx2
from fastmcp import Client
from fastmcp.client.transports import SSETransport, StreamableHttpTransport
from fastmcp.mcp_config import infer_transport_type_from_url
from mcp.shared._httpx_utils import create_mcp_http_client

from app.exceptions import McpToolError
from app.logging_utils import http_status_text
from shared.models.tools import McpToolData

_ALLOWED_TRANSPORT_PREFIXES = ("http://", "https://")


class _StatusRecordingHttpTransport(StreamableHttpTransport):
    """Streamable HTTP transport that remembers the status of its latest failed POST.

    mcp 2 answers a 4xx/5xx that carries no JSON-RPC error (an expired token's 401,
    a proxy's 503) with a generic "Server returned an error response"; the recorded
    status lets the error name the cause.
    """

    def __init__(self, url: str) -> None:
        super().__init__(url, httpx_client_factory=self._build_http_client)
        self.last_post_error_code: int | None = None

    def _build_http_client(
        self,
        headers: dict[str, str] | None = None,
        timeout: httpx2.Timeout | None = None,
        auth: httpx2.Auth | None = None,
        follow_redirects: bool = True,
    ) -> httpx2.AsyncClient:
        # The parameters are exactly what fastmcp passes, so a new one fails loudly
        # instead of being dropped. The SDK's own builder keeps timeouts as in the
        # default client; follow_redirects is ignored to keep that client's
        # behaviour too, where the SDK follows same-origin redirects only.
        http_client = create_mcp_http_client(headers=headers, timeout=timeout, auth=auth)
        http_client.event_hooks.setdefault("response", []).append(self._record_post_status)
        return http_client

    async def _record_post_status(self, response: httpx2.Response) -> None:
        # Requests travel in POSTs; the GET stream and the closing DELETE are
        # answered 405 by many healthy servers.
        if response.request.method != "POST":
            return
        # A successful POST clears it, so an earlier refusal -- such as the 400 a
        # handshake-era server gives the server/discover probe -- is never blamed
        # for a later failure.
        self.last_post_error_code = response.status_code if response.status_code >= 400 else None


def http_error_status(client: Client) -> str | None:
    """Name the HTTP status of the client's latest failed POST, e.g. "HTTP 401 Unauthorized".

    Returns None when the latest POST succeeded or the transport records no status
    (SSE, whose failures raise an httpx2.HTTPStatusError that carries it).
    """
    transport = client.transport
    if not isinstance(transport, _StatusRecordingHttpTransport):
        return None
    code = transport.last_post_error_code
    if code is None:
        return None
    return http_status_text(code)


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
        if not self._is_http_url(data.transport):
            raise McpToolError(
                f"MCP tool '{data.tool_name}' has an invalid transport: "
                "it must be an http:// or https:// URL with a host."
            )
        url, userinfo_auth = self._split_userinfo(data.transport)

        transport_class = (
            SSETransport
            if infer_transport_type_from_url(url) == "sse"
            else _StatusRecordingHttpTransport
        )
        return Client(
            transport=transport_class(url),
            timeout=data.timeout,
            auth=data.auth or userinfo_auth,
            init_timeout=data.init_timeout,
        )

    @staticmethod
    def _split_userinfo(url: str) -> tuple[str, httpx2.BasicAuth | None]:
        # Credentials left in the URL are quoted wherever the SDK or httpx2 renders it:
        # status errors, and the SSE message endpoint, which is joined onto this URL and
        # shows up in the SDK's own error log. httpx2 sends URL userinfo as Basic auth
        # when no other auth is set, and ignores it otherwise; this keeps both.
        parts = urlsplit(url)
        userinfo, separator, host = parts.netloc.rpartition("@")
        if not separator:
            return url, None
        user, _, password = userinfo.partition(":")
        user, password = unquote(user), unquote(password)
        basic_auth = httpx2.BasicAuth(user, password) if user or password else None
        return urlunsplit(parts._replace(netloc=host)), basic_auth

    @staticmethod
    def _is_http_url(url: str) -> bool:
        if not url.startswith(_ALLOWED_TRANSPORT_PREFIXES):
            return False
        try:
            return bool(urlparse(url).netloc)
        except ValueError:
            return False
