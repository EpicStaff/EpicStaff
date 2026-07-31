from fastmcp import FastMCP
from browser_runner import run_browser_task
from config import DEEPSEEK_API_KEY

mcp = FastMCP("custom_tools MCP Server")


@mcp.tool()
async def run_browser(
    prompt: str,
    model: str = "deepseek-chat",
    temperature: float = 0.0,
):
    if not DEEPSEEK_API_KEY:
        return {"ok": False, "error": "DEEPSEEK_API_KEY not set"}
    try:
        result = await run_browser_task(prompt, model=model, temperature=temperature)
        return {
            "ok": True,
            "output": getattr(result, "output", None),
            "errors": result.errors() if hasattr(result, "errors") else None,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


if __name__ == "__main__":
    mcp.run("streamable-http")
