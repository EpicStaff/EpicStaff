# use fast mcp client to connect with servers in docker container using http protocol
import os
import asyncio
import json
from fastmcp import Client
from prompt import TASK_PROMPT

FASTMCP_URL = os.getenv("FASTMCP_URL", "http://127.0.0.1:8080/mcp")


async def main():
    async with Client(FASTMCP_URL, timeout=300) as client:
        resp = await client.call_tool("run_computer", {"prompt": TASK_PROMPT})

        if hasattr(resp, "dict"):
            resp = resp.dict()

        print(json.dumps(resp, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
