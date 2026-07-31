import asyncio
from fastmcp import Client

MCP_URL = "http://127.0.0.1:8080/mcp"


async def main():
    async with Client(MCP_URL) as client:
        tools = await client.list_tools()
        print("Available tools:")
        for t in tools:
            print(f"- {t.name}: {t.description}")


if __name__ == "__main__":
    asyncio.run(main())
