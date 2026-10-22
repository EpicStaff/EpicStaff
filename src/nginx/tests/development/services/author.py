"""A frontend development server on the developer's machine, as the development lab sees it.

It answers every path with what reached it (raw path and headers), serves server-sent events on
`/sse` and a WebSocket echo on `/ws`, the two ways development servers reload a page, and sends
every header nginx must keep from the browser: a cookie, a framing rule, a policy of its own,
Clear-Site-Data and the gateway's marker. Its caching header must pass through.
"""

import asyncio
import os

from aiohttp import WSMsgType, web

PORT = int(os.environ["PORT"])


def raw_headers(request: web.Request) -> list[list[str]]:
    return [
        [name.decode("latin-1"), value.decode("latin-1")] for name, value in request.raw_headers
    ]


async def server_sent_events(request: web.Request) -> web.StreamResponse:
    # Like esbuild's live-reload stream: only for a request that asks for an event stream, so the
    # browser's Accept header must reach the development server.
    if "text/event-stream" not in request.headers.get("Accept", ""):
        return web.Response(status=406, text="Ask for text/event-stream.")
    response = web.StreamResponse(
        headers={"Content-Type": "text/event-stream", "Cache-Control": "no-cache"}
    )
    await response.prepare(request)
    for index in range(4):
        await response.write(f"data: change={index}\n\n".encode())
        await asyncio.sleep(0.5)
    await response.write_eof()
    return response


async def websocket_echo(request: web.Request) -> web.WebSocketResponse:
    websocket = web.WebSocketResponse()
    await websocket.prepare(request)
    await websocket.send_json({"author": True, "headers": raw_headers(request)})
    async for message in websocket:
        if message.type == WSMsgType.TEXT:
            await websocket.send_str(f"echo:{message.data}")
    return websocket


async def handle(request: web.Request) -> web.StreamResponse:
    path = request.raw_path.split("?", 1)[0]
    if path == "/sse":
        return await server_sent_events(request)
    if path == "/ws":
        return await websocket_echo(request)
    await request.read()
    response = web.json_response(
        {"author": True, "raw_path": request.raw_path, "headers": raw_headers(request)}
    )
    response.headers["Set-Cookie"] = "planted=1; Domain=epicstaff.localhost; Path=/"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy"] = "default-src 'none'"
    response.headers["Clear-Site-Data"] = '"cookies"'
    response.headers["X-EpicStaff-Gateway-Deny"] = "forbidden"
    response.headers["Cache-Control"] = "max-age=60"
    return response


app = web.Application()
app.router.add_route("*", "/{tail:.*}", handle)

if __name__ == "__main__":
    web.run_app(app, port=PORT, access_log=None, print=None)
