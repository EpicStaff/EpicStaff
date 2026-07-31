import asyncio
from fastmcp import Client

MCP_URL = "http://127.0.0.1:8080/mcp"


async def main():
    async with Client(MCP_URL) as client:
        result = await client.call_tool(
            "run_computer",
            {
                "prompt": "Open the terminal and type 'echo Hello World'",
                "env": "local",
                "params": {},
            },
        )
        print("Result:", result)


if __name__ == "__main__":
    asyncio.run(main())
