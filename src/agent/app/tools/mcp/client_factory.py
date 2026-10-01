from __future__ import annotations

from fastmcp import Client
from shared.models.tools import McpToolData


class FastMCPClientFactory:
    """Pure Fabrication: builds a fastmcp Client from McpToolData config.

    Wraps the fastmcp library behind a stable interface so the rest of the
    code is not coupled to Client construction details.
    """

    def create(self, data: McpToolData) -> Client:
        # data.transport is unvalidated (no scheme/private-range check) -- accepted,
        # Won't Fix: an operator/member configures this endpoint and what it points at
        # is their responsibility, per design. Don't re-flag as an SSRF gap without new
        # information (e.g. a path letting one org's config affect another org's
        # request). Separate from, and does not close, the risk of trusting the
        # connected server's own description/inputSchema -- see McpToolGateway.
        return Client(
            transport=data.transport,
            timeout=data.timeout,
            auth=data.auth or None,
            init_timeout=data.init_timeout,
        )
