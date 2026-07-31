from fastmcp import FastMCP
from computer_runner import run_computer_task

mcp = FastMCP("computer_use MCP Server")


@mcp.tool()
async def run_computer(
    prompt: str,
    env: str = "docker",
    params: dict | None = None,
):
    try:
        result = await run_computer_task(prompt=prompt, env=env, params=params)
        return {"ok": True, "output": result}
    except Exception as e:
        return {"ok": False, "error": str(e)}


if __name__ == "__main__":
    mcp.run("streamable-http")
