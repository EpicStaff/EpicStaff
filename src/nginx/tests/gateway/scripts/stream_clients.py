"""SSE and WebSocket through the gateway (run in the tools container). Exits 1 on a failure."""

import asyncio
import sys
import time

import aiohttp

GATEWAY = "http://nginx"
HOST = {"Host": "alpha.plugins.epicstaff.test"}


async def server_sent_events(session: aiohttp.ClientSession) -> bool:
    arrivals = []
    started = time.monotonic()
    async with session.get(f"{GATEWAY}/api/public/sse", headers=HOST) as response:
        async for line in response.content:
            if line.strip():
                arrivals.append(round(time.monotonic() - started, 2))
    gaps = [later - earlier for earlier, later in zip(arrivals, arrivals[1:], strict=False)]
    print(f"   SSE events arrived at {arrivals} s")
    # The backend writes one event every 0.5 s; a buffering proxy would deliver them at once.
    return len(arrivals) == 4 and all(gap > 0.3 for gap in gaps)


async def websocket(session: aiohttp.ClientSession) -> bool:
    async with session.ws_connect(f"{GATEWAY}/api/public/ws", headers=HOST) as connection:
        first = await connection.receive_json()
        await connection.send_str("ping")
        echoed = await connection.receive_str()
    names = [name.lower() for name, _ in first["headers"]]
    print(f"   WebSocket upgraded; the plugin saw {sorted(set(names))}; echo {echoed!r}")
    upgraded = echoed == "echo:ping" and "cookie" not in names
    try:
        async with session.ws_connect(f"{GATEWAY}/api/private/ws", headers=HOST):
            print("   UNEXPECTED: a WebSocket on a path that is not public was upgraded without login")
            return False
    except aiohttp.WSServerHandshakeError as error:
        print(f"   WebSocket without login refused: {error.status}")
        return upgraded and error.status == 401


async def main() -> int:
    async with aiohttp.ClientSession(cookies={"sessionid": "s3cret"}) as session:
        results = [await server_sent_events(session), await websocket(session)]
    return 0 if all(results) else 1


sys.exit(asyncio.run(main()))
