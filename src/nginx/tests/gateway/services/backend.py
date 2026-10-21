"""A plugin backend for the gateway lab: echoes what reached it, serves SSE and a WebSocket.

Routes on the raw path, so the evidence shows exactly what nginx forwarded. A request whose raw
path mentions _epicstaff is recorded in EVIDENCE_FILE: none may ever arrive.
"""

import asyncio
import os

from aiohttp import WSMsgType, web

NAME = os.environ["BACKEND_NAME"]
PORT = int(os.environ["PORT"])
EVIDENCE_FILE = os.environ["EVIDENCE_FILE"]


def raw_headers(request: web.Request) -> list[list[str]]:
    return [[name.decode("latin-1"), value.decode("latin-1")] for name, value in request.raw_headers]


async def server_sent_events(request: web.Request) -> web.StreamResponse:
    response = web.StreamResponse(headers={"Content-Type": "text/event-stream", "Cache-Control": "no-cache"})
    await response.prepare(request)
    for index in range(4):
        await response.write(f"data: event={index}\n\n".encode())
        await asyncio.sleep(0.5)
    await response.write_eof()
    return response


async def websocket_echo(request: web.Request) -> web.WebSocketResponse:
    websocket = web.WebSocketResponse()
    await websocket.prepare(request)
    await websocket.send_json({"backend": NAME, "headers": raw_headers(request)})
    async for message in websocket:
        if message.type == WSMsgType.TEXT:
            await websocket.send_str(f"echo:{message.data}")
    return websocket


async def handle(request: web.Request) -> web.StreamResponse:
    raw_path = request.raw_path
    if "_epicstaff" in raw_path:
        with open(EVIDENCE_FILE, "a", encoding="utf-8") as evidence:
            evidence.write(f"REACHED-EPICSTAFF {NAME} {raw_path}\n")
    path = raw_path.split("?", 1)[0]
    if path.endswith("/sse"):
        return await server_sent_events(request)
    if path.endswith("/ws"):
        return await websocket_echo(request)
    if path.endswith("/accel"):
        return web.Response(text="BACKEND-BODY", headers={"X-Accel-Redirect": "/_plugin_gateway_check"})
    if path.endswith("/bench"):
        return web.Response(text="ok")
    if path.endswith("/denied"):
        # The plugin's own refusal, dressed as the gateway's: nginx must hide the marker.
        denied = web.json_response({"code": "login_required"}, status=401)
        denied.headers.add("X-EpicStaff-Gateway-Deny", "login")
        denied.headers.add("x-epicstaff-gateway-deny", "forbidden")
        return denied
    body = await request.read()
    response = web.json_response(
        {"backend": NAME, "method": request.method, "raw_path": raw_path, "body_bytes": len(body),
         "headers": raw_headers(request)}
    )
    # None may reach the browser: a cookie for the parent domain, a framing rule, and the
    # gateway's refusal marker.
    response.headers["Set-Cookie"] = "tossed=1; Domain=epicstaff.test; Path=/"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-EpicStaff-Gateway-Deny"] = "forbidden"
    return response


app = web.Application(client_max_size=64 * 1024 * 1024)
app.router.add_route("*", "/{tail:.*}", handle)

if __name__ == "__main__":
    web.run_app(app, port=PORT, access_log=None, print=None)
