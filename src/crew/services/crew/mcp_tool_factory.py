import asyncio
from functools import partial

from fastmcp import Client
from mcp.types import Tool as FastMCPTool

from crewai.tools.base_tool import Tool as CrewaiTool
from src.crew.utils.sync_wrapper import sync_wrapper
from src.shared.models import McpToolData

from src.crew.services.schema_converter.converter import generate_model_from_schema
from src.crew.services.graph.events import StopEvent


class McpTool:
    def __init__(
        self,
        fast_mcp_client: Client,
        tool_name: str,
        stop_event: StopEvent | None = None,
    ):
        self.fast_mcp_client = fast_mcp_client
        self.tool_name = tool_name
        self.stop_event = stop_event

    async def get_tool_data(self) -> FastMCPTool:
        # List all tools from the server
        async with self.fast_mcp_client:
            tools = await self.fast_mcp_client.list_tools()

        # Find the tool by name
        tool: FastMCPTool = next((t for t in tools if t.name == self.tool_name), None)
        if not tool:
            raise ValueError(f"Tool {self.tool_name} not found")

        return tool

    async def execute(self, stop_event: StopEvent | None = None, **kwargs):
        async with self.fast_mcp_client:
            task = asyncio.create_task(
                self.fast_mcp_client.call_tool(self.tool_name, arguments=kwargs)
            )

            while not task.done():
                if stop_event is not None:
                    stop_event.check_stop()
                await asyncio.sleep(0.01)

            result = await task

            if result.is_error:
                raise RuntimeError(result.data)

            if result.structured_content:
                return result.structured_content

            if result.content:
                return " ".join([c.text for c in result.content if hasattr(c, "text")])

            return result.data


class CrewaiMcpToolFactory:
    async def create(
        self, tool_data: McpToolData, stop_event: StopEvent | None = None
    ) -> CrewaiTool:
        mcp_tool = McpTool(
            fast_mcp_client=Client(
                transport=tool_data.transport,
                timeout=tool_data.timeout,
                auth=tool_data.auth if tool_data.auth else None,
                init_timeout=tool_data.init_timeout,
            ),
            tool_name=tool_data.tool_name,
            stop_event=stop_event,
        )
        tool = await mcp_tool.get_tool_data()

        config = {
            "name": tool_data.tool_name,
            "description": tool.description or tool_data.tool_name,
        }
        if tool.inputSchema:
            title = tool_data.tool_name
            tool.inputSchema["title"] = title
            args_schema = generate_model_from_schema(schema_dict=tool.inputSchema)
            config["args_schema"] = args_schema
        config["func"] = partial(sync_wrapper, mcp_tool.execute)
        return CrewaiTool(**config)
