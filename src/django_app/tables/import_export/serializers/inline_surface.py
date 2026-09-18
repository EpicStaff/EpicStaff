from tables.import_export.enums import EntityType


def serialize_inline_surface(inline_surface) -> dict:
    return {
        "instructions": inline_surface.instructions,
        "tools": {
            EntityType.PYTHON_CODE_TOOL: list(
                inline_surface.python_tools.values("python_tool_id", "mode")
            ),
            EntityType.MCP_TOOL: list(
                inline_surface.mcp_tools.values("mcp_tool_id", "mode")
            ),
        },
    }
