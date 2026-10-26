"""Stand-in for django_app in the development lab: nginx's two checks, and an echo of the API.

- `GET /api/plugin-gateway/check/`: the gateway check for the plugin `alpha`, whose backend is
  the lab's plugin backend: 404 without the shared secret, otherwise 200 with its upstream. The
  lab tests nginx, not the decision, so every request of `alpha` is allowed.
- `GET /api/plugin-gateway/development-spa/`: the page decision, answered the way the lab last
  set it (`POST /lab/page-decision`), and counted (`GET /lab/page-decisions`, which also returns
  the headers of the last one). For a development server it answers with an address, never a
  name: it resolves AUTHOR_HOST itself, as django_app resolves host.docker.internal.
- Every other path echoes the headers that reached "Django", for the API listeners' checks.
"""

import hmac
import os
import socket

from aiohttp import web

GATEWAY_SECRET = os.environ["PLUGINS_GATEWAY_SECRET"]
PORT = int(os.environ["PORT"])
AUTHOR_HOST = os.environ["AUTHOR_HOST"]
PLUGIN_UPSTREAM = os.environ["PLUGIN_UPSTREAM"]

page_decision = {"answer": "published"}
page_decisions = {"count": 0, "last_headers": []}


def raw_headers(request: web.Request) -> list[list[str]]:
    return [
        [name.decode("latin-1"), value.decode("latin-1")] for name, value in request.raw_headers
    ]


def holds_secret(request: web.Request) -> bool:
    return hmac.compare_digest(request.headers.get("X-Plugin-Gateway-Secret", ""), GATEWAY_SECRET)


async def gateway_check(request: web.Request) -> web.Response:
    if not holds_secret(request):
        return web.Response(status=404)
    if request.headers.get("X-Plugin-Identifier") != "alpha":
        return web.Response(status=403, headers={"X-Plugin-Deny": "not_found"})
    return web.Response(
        status=200,
        headers={
            "X-Plugin-Upstream": PLUGIN_UPSTREAM,
            "X-Plugin-Context": "lab-context",
            "X-Plugin-Forward-Authorization": "0",
        },
    )


async def development_page_check(request: web.Request) -> web.Response:
    page_decisions["count"] += 1
    page_decisions["last_headers"] = raw_headers(request)
    if not holds_secret(request):
        return web.Response(status=404)
    answer = page_decision["answer"]
    if answer == "published":
        return web.Response(status=204)
    if answer == "development":
        address = socket.gethostbyname(AUTHOR_HOST)
        return web.Response(
            status=403, headers={"X-Plugin-Spa-Upstream": f"{address}:{page_decision['port']}"}
        )
    if answer == "unresolved":
        return web.Response(status=403)
    if answer == "error":
        return web.Response(status=500, text="Internal Server Error")
    # "drop": the connection closes without an answer, as when django_app goes away.
    request.transport.close()
    return web.Response(status=204)


async def set_page_decision(request: web.Request) -> web.Response:
    page_decision.clear()
    page_decision.update(await request.json())
    return web.json_response(page_decision)


async def get_page_decisions(request: web.Request) -> web.Response:
    return web.json_response(page_decisions)


async def django_api(request: web.Request) -> web.Response:
    await request.read()
    return web.json_response(
        {"django": True, "path": request.raw_path, "headers": raw_headers(request)}
    )


app = web.Application()
app.router.add_get("/api/plugin-gateway/check/", gateway_check)
app.router.add_get("/api/plugin-gateway/development-spa/", development_page_check)
app.router.add_post("/lab/page-decision", set_page_decision)
app.router.add_get("/lab/page-decisions", get_page_decisions)
app.router.add_route("*", "/{tail:.*}", django_api)

if __name__ == "__main__":
    web.run_app(app, port=PORT, access_log=None, print=None)
