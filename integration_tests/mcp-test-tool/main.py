from fastmcp import FastMCP

mcp = FastMCP("MyServer")

@mcp.tool
def test_tool_1(name: str) -> str:
    return f"Hello, {name}!"

if __name__ == "__main__":
    # Start an HTTP server on port 8000
    mcp.run(transport="http", host="0.0.0.0", port=8000)