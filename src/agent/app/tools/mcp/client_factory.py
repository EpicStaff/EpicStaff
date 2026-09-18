from __future__ import annotations

from fastmcp import Client

from shared.models.tools import McpToolData


class FastMCPClientFactory:
    """Pure Fabrication: builds a fastmcp Client from McpToolData config.

    Wraps the fastmcp library behind a stable interface so the rest of the
    code is not coupled to Client construction details.
    """

    def create(self, data: McpToolData) -> Client:
        return Client(
            transport=data.transport,
            timeout=data.timeout,
            auth=data.auth or None,
            init_timeout=data.init_timeout,
        )
