"""Live reload through the page proxy (run in the tools container): server-sent events arrive as
they are sent, and a WebSocket upgrades (101) and echoes. Exits 1 on a failure."""

import asyncio
import sys
import time

import aiohttp

GATEWAY = "http://nginx"
HOST = {"Host": "alpha.plugins.epicstaff.localhost"}


async def server_sent_events(session: aiohttp.ClientSession) -> bool:
    arrivals = []
    started = time.monotonic()
    # The development server streams only to a request that asks for an event stream.
    headers = {**HOST, "Accept": "text/event-stream"}
    async with session.get(f"{GATEWAY}/sse", headers=headers) as response:
        status = response.status
        async for line in response.content:
            if line.strip():
                arrivals.append(round(time.monotonic() - started, 2))
    gaps = [later - earlier for earlier, later in zip(arrivals, arrivals[1:], strict=False)]
    print(f"   SSE ({status}) events arrived at {arrivals} s")
    # The server writes one event every 0.5 s: a buffering proxy would deliver them at once, at
    # the end of the stream.
    return status == 200 and len(arrivals) == 4 and all(gap > 0.3 for gap in gaps)


async def websocket(session: aiohttp.ClientSession) -> bool:
    async with session.ws_connect(f"{GATEWAY}/ws", headers=HOST) as connection:
        first = await connection.receive_json()
        await connection.send_str("reload")
        echoed = await connection.receive_str()
    names = sorted({name.lower() for name, _ in first["headers"]})
    print(f"   WebSocket upgraded; the development server saw {names}; echo {echoed!r}")
    return first.get("author") is True and echoed == "echo:reload" and "cookie" not in names


async def main() -> int:
    async with aiohttp.ClientSession(cookies={"sessionid": "s3cret"}) as session:
        results = [await server_sent_events(session), await websocket(session)]
    return 0 if all(results) else 1


sys.exit(asyncio.run(main()))
