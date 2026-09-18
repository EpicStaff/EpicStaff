from __future__ import annotations

from shared.models.agent_service import ToolResult
from shared.models.tools import McpToolData

from app.exceptions import McpToolError
from app.tools.mcp.gateway import McpToolGateway


class McpToolExecutor:
    """Executes an MCP tool via McpToolGateway and maps the result to ToolResult.

    Analogous to PythonCodeToolExecutor: adapts the gateway's raw str / error
    into the ToolResult contract expected by ToolRegistry.
    """

    def __init__(self, gateway: McpToolGateway, data: McpToolData, name: str) -> None:
        self._gateway = gateway
        self._data = data
        self._name = name

    async def __call__(self, args: dict) -> ToolResult:
        try:
            content = await self._gateway.call(self._data, args)

        except McpToolError as error:
            return ToolResult(tool_call_id="", content=str(error), is_error=True)

        return ToolResult(tool_call_id="", content=content, is_error=False)
